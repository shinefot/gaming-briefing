"""Tests for the spine and all data-plane lanes.

Store tests use a REAL temporary SQLite database (no mocking) so they prove
persistence works. Fetcher tests inject a fake HTTP session so they prove the
parsing and graceful-failure logic without touching the network.
"""
import tempfile
from datetime import date, timedelta
from pathlib import Path

import requests

from briefing.fetchers import finnhub, sec, steam
from briefing.models import Doc, Metric, utcnow
from briefing.store import Store


# ----------------------------- fakes -----------------------------

class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _SteamSession:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, params=None, timeout=None):
        val = self.mapping[params["appid"]]
        if isinstance(val, Exception):
            raise val
        return _Resp(val)


class _SecSession:
    def __init__(self, ticker_map, submissions):
        self.ticker_map = ticker_map
        self.submissions = submissions

    def get(self, url, headers=None, params=None, timeout=None):
        if "company_tickers" in url:
            return _Resp(self.ticker_map)
        return _Resp(self.submissions)


class _FinnhubSession:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, params=None, timeout=None):
        val = self.mapping[params["symbol"]]
        if isinstance(val, Exception):
            raise val
        return _Resp(val)


def _ccu(count):
    return {"response": {"player_count": count, "result": 1}}


# --------------------------- store tests --------------------------

def test_metric_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        store.upsert_metrics([Metric("steam_ccu", "570", 900000, "steam")])
        out = store.metrics_for("steam_ccu", "570")
        assert len(out) == 1 and out[0].value == 900000
        store.close()


def test_metric_same_day_upserts_not_duplicates():
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        now = utcnow()
        store.upsert_metrics([Metric("steam_ccu", "570", 100, "steam", observed_at=now)])
        store.upsert_metrics([Metric("steam_ccu", "570", 200, "steam", observed_at=now)])
        out = store.metrics_for("steam_ccu", "570")
        assert len(out) == 1 and out[0].value == 200
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
        assert [m.value for m in out] == [100, 150]
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
        assert len(out) == 1 and out[0].entities == ["TTWO"] and out[0].extra["form"] == "8-K"
        store.close()


# --------------------------- steam tests --------------------------

def test_steam_fetch_parses_player_count():
    session = _SteamSession({"570": _ccu(912345)})
    assert steam.fetch_current_players("570", session=session) == 912345


def test_steam_poll_skips_failing_appid_gracefully():
    session = _SteamSession({
        "570": _ccu(900000),
        "999": requests.Timeout("boom"),
        "730": _ccu(1100000),
    })
    metrics = steam.poll(["570", "999", "730"], session=session)
    assert {m.entity for m in metrics} == {"570", "730"}


# ---------------------------- sec tests ---------------------------

def test_sec_keeps_only_material_recent_filings():
    recent = (date.today() - timedelta(days=2)).isoformat()
    submissions = {"filings": {"recent": {
        "form":                   ["8-K",   "10-K",       "4"],
        "filingDate":             [recent,  "2000-01-01", recent],
        "accessionNumber":        ["0000866787-26-000010", "0000866787-00-000001", "0000866787-26-000011"],
        "primaryDocument":        ["a.htm", "b.htm",      "c.htm"],
        "primaryDocDescription":  ["Material event", "Annual report", "Insider"],
    }}}
    ticker_map = {"0": {"cik_str": 866787, "ticker": "TTWO", "title": "TAKE-TWO"}}
    session = _SecSession(ticker_map, submissions)

    docs = sec.fetch({"Take-Two": {"ticker": "TTWO", "appids": []}}, session=session)
    # 10-K is too old, form "4" isn't material -> only the 8-K survives
    assert len(docs) == 1
    assert docs[0].extra["form"] == "8-K"
    assert docs[0].entities == ["TTWO"]
    assert docs[0].url.startswith("https://www.sec.gov/Archives/edgar/data/866787/")


def test_sec_skips_ticker_not_in_edgar():
    ticker_map = {"0": {"cik_str": 866787, "ticker": "TTWO", "title": "TAKE-TWO"}}
    session = _SecSession(ticker_map, {"filings": {"recent": {}}})
    docs = sec.fetch({"Capcom": {"ticker": "CCOEY", "appids": []}}, session=session)
    assert docs == []


# -------------------------- finnhub tests -------------------------

def test_finnhub_parses_price():
    session = _FinnhubSession({"TTWO": {"c": 152.3, "pc": 150.0}})
    assert finnhub.fetch_quote("TTWO", "key", session=session) == 152.3


def test_finnhub_skips_unknown_symbol():
    session = _FinnhubSession({
        "TTWO": {"c": 150.0, "pc": 149.0},
        "XXXX": {"c": 0, "pc": 0},      # unknown symbol -> zeros
    })
    out = finnhub.fetch(["TTWO", "XXXX"], "key", session=session)
    assert {m.entity for m in out} == {"TTWO"}
    assert out[0].metric == "stock_price"


# --------------------------- brief tests --------------------------

def _seed_brief_data(store):
    """Put a little of each data type in the store for brief tests."""
    from briefing.models import Doc
    store.upsert_metrics([
        Metric("steam_ccu", "1174180", 32000, "steam"),
        Metric("stock_price", "TTWO", 228.90, "finnhub"),
    ])
    store.upsert_docs([Doc(
        source="sec_edgar", section="financials",
        title="TTWO filed 8-K on 2026-05-21", url="https://sec.gov/x",
        entities=["TTWO"], extra={"form": "8-K", "filing_date": "2026-05-21"},
    )])


def test_gather_facts_includes_real_numbers():
    from briefing import brief
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        _seed_brief_data(store)
        facts = brief.gather_facts(store)
        # the exact figures from the DB must appear in the factual block
        assert "32,000 players" in facts
        assert "$228.90" in facts
        assert "8-K" in facts
        store.close()


def test_generate_uses_injected_writer_and_wraps_with_header():
    from briefing import brief
    with tempfile.TemporaryDirectory() as d:
        store = Store(Path(d) / "t.db")
        store.init()
        _seed_brief_data(store)
        # fake writer stands in for Claude — proves no network/key needed to test
        captured = {}
        def fake_writer(facts):
            captured["facts"] = facts
            return "FAKE BRIEF BODY"
        out = brief.generate(store, writer=fake_writer)
        assert "FAKE BRIEF BODY" in out
        assert out.startswith("# Gaming Industry Briefing —")
        # the writer must have been handed the real numbers
        assert "$228.90" in captured["facts"]
        store.close()
