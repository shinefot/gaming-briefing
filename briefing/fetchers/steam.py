"""Steam poller — lane 2 (Community & Hype).

Steam's Web API gives only a single point-in-time number per game; it stores no
history. So we build the time-series ourselves: poll once per scheduled run,
store one point per game per day. The dataset that doesn't exist off the shelf
is the thing this lane demonstrates.

The GetNumberOfCurrentPlayers endpoint needs no API key.
"""
from __future__ import annotations

import requests

from ..models import Metric

STEAM_CCU_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)


def fetch_current_players(appid: str, session=None, timeout: int = 15) -> int | None:
    """Return current concurrent players for one appid, or None if unavailable.

    `session` is injectable so this is testable without hitting the network.
    Response shape: {"response": {"player_count": 12345, "result": 1}}
    """
    http = session or requests
    resp = http.get(STEAM_CCU_URL, params={"appid": appid}, timeout=timeout)
    resp.raise_for_status()
    body = resp.json().get("response", {})
    if body.get("result") != 1:
        return None
    return body.get("player_count")


def poll(appids: list[str], session=None, source: str = "steam") -> list[Metric]:
    """Poll every appid, returning a Metric per game that responded.

    Graceful degradation: a single appid failing (rate limit, timeout, bad id)
    is logged and skipped — it never takes down the rest of the run.
    """
    metrics: list[Metric] = []
    for appid in appids:
        try:
            count = fetch_current_players(appid, session=session)
        except Exception as exc:  # noqa: BLE001 — intentional catch-all per appid
            print(f"[steam] appid {appid} failed: {exc}")
            continue
        if count is None:
            print(f"[steam] appid {appid} returned no data")
            continue
        metrics.append(
            Metric(metric="steam_ccu", entity=appid, value=float(count), source=source)
        )
    return metrics
