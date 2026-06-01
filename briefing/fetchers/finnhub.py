"""Finnhub fetcher — lane 1b (Market & Financials: stock prices).

Free tier: 60 calls/min, far more than a daily run over a dozen tickers needs.
US-listed tickers return clean quotes; some foreign OTC tickers come back with
price 0 (no data) and are skipped gracefully.
"""
from __future__ import annotations

import requests

from ..models import Metric

QUOTE_URL = "https://finnhub.io/api/v1/quote"


def fetch_quote(symbol: str, api_key: str, session=None, timeout: int = 15) -> float | None:
    """Latest price for one symbol, or None if Finnhub has no data for it.

    Response shape: {"c": current, "h": high, "l": low, "o": open, "pc": prev_close}
    Unknown symbols return all zeros, which we treat as 'no data'.
    """
    http = session or requests
    resp = http.get(QUOTE_URL, params={"symbol": symbol, "token": api_key}, timeout=timeout)
    resp.raise_for_status()
    price = resp.json().get("c", 0)
    if not price:  # 0 or missing -> no data for this symbol
        return None
    return float(price)


def fetch(tickers: list[str], api_key: str, session=None) -> list[Metric]:
    """One Metric per ticker that returned a price. Graceful per ticker."""
    metrics: list[Metric] = []
    for sym in tickers:
        try:
            price = fetch_quote(sym, api_key, session=session)
        except Exception as exc:  # noqa: BLE001
            print(f"[finnhub] {sym} failed: {exc}")
            continue
        if price is None:
            print(f"[finnhub] {sym} returned no price — skipped")
            continue
        metrics.append(
            Metric(metric="stock_price", entity=sym, value=price, source="finnhub")
        )
    return metrics
