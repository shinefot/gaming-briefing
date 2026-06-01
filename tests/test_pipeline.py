"""Tests for the spine and the Steam lane.

The store tests use a REAL temporary SQLite database (no mocking) so they prove
persistence actually works. The Steam tests inject a fake HTTP session so they
prove the parsing and graceful-failure logic without touching the network.
"""
import tempfile
from datetime import timedelta
from pathlib import Path

import requests

from briefing.fetchers import steam
from briefing.models import Doc, Metric, utcnow
from briefing.store import Store


# ----------------------------- fakes -----------------------------

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    """Maps appid -> payload dict, or an Exception to raise."""
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, params=None, timeout=None):
        val = self.mapping[params["appid"]]
        if isinstance(val, Exception):
            raise val
        return _FakeResp(val)


def _ccu_payload(count):
    return {"response": {"player_count": count, "result": 1}}


# --------------------------- store tests --------------------------

def test_metric_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        store.upsert_metrics([Metric(metric="steam_ccu", entity="570", value=900000, source="steam")])
        out = store.metrics_for("steam_ccu", "570")
        assert len(out) == 1
        assert out[0].value == 900000
        assert out[0].entity == "570"
        store.close()


def test_metric_same_day_upserts_not_duplicates():
    """Two polls of the same game on the same day collapse to one row."""
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        now = utcnow()
        store.upsert_metrics([Metric("steam_ccu", "570", 100, "steam", observed_at=now)])
        store.upsert_metrics([Metric("steam_ccu", "570", 200, "steam", observed_at=now)])
        out = store.metrics_for("steam_ccu", "570")
        assert len(out) == 1            # not 2
        assert out[0].value == 200      # last write wins
        store.close()


def test_metric_series_accumulates_across_days():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        today = utcnow()
        yesterday = today - timedelta(days=1)
        store.upsert_metrics([
            Metric("steam_ccu", "570", 100, "steam", observed_at=yesterday),
            Metric("steam_ccu", "570", 150, "steam", observed_at=today),
        ])
        out = store.metrics_for("steam_ccu", "570")
        assert [m.value for m in out] == [100, 150]   # ordered oldest -> newest
        store.close()


def test_doc_roundtrip_preserves_entities_and_extra():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        store.upsert_docs([Doc(
            source="sec_edgar", section="financials",
            title="Take-Two 8-K", url="https://example.com/ttwo-8k",
            entities=["TTWO"], extra={"form": "8-K"},
        )])
        out = store.docs_for("financials")
        assert len(out) == 1
        assert out[0].entities == ["TTWO"]
        assert out[0].extra["form"] == "8-K"
        store.close()


# --------------------------- steam tests --------------------------

def test_fetch_parses_player_count():
    session = _FakeSession({"570": _ccu_payload(912345)})
    assert steam.fetch_current_players("570", session=session) == 912345


def test_poll_skips_failing_appid_gracefully():
    session = _FakeSession({
        "570": _ccu_payload(900000),
        "999": requests.Timeout("boom"),     # this one fails
        "730": _ccu_payload(1100000),
    })
    metrics = steam.poll(["570", "999", "730"], session=session)
    # the failing appid is skipped, the other two survive
    assert {m.entity for m in metrics} == {"570", "730"}
    assert len(metrics) == 2
