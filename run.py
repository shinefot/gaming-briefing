"""Pipeline entry point.

Run with:  python run.py

Runs the data plane: fetch from each source, normalize, store. Two lanes are
live now — Community (Steam) and Market & Financials (SEC filings + stock
prices). The reasoning plane (turning stored facts into a written briefing)
comes next. Every lane fails gracefully: a dead source produces a smaller
number, never a crash.
"""
from briefing.config import (
    DB_PATH, FINNHUB_API_KEY, ANTHROPIC_API_KEY, TRACKED, all_appids, all_tickers,
)
from briefing.fetchers import finnhub, sec, steam
from briefing.store import Store
from briefing import brief
from briefing.models import utcnow
from pathlib import Path


def run_data_plane() -> None:
    store = Store(DB_PATH)
    store.init()

    # --- Community lane: Steam concurrent players ---
    appids = all_appids()
    metrics = steam.poll(appids)
    print(f"[data-plane] steam:   polled {len(appids)} appids, stored {store.upsert_metrics(metrics)} metrics")

    # --- Financials lane (a): SEC filings ---
    docs = sec.fetch(TRACKED)
    print(f"[data-plane] sec:     found {len(docs)} filings, stored {store.upsert_docs(docs)} docs")

    # --- Financials lane (b): stock prices ---
    if FINNHUB_API_KEY:
        prices = finnhub.fetch(all_tickers(), FINNHUB_API_KEY)
        print(f"[data-plane] finnhub: got {len(prices)} prices, stored {store.upsert_metrics(prices)} metrics")
    else:
        print("[data-plane] finnhub: no API key in .env — skipping prices")

    # --- Reasoning plane: write the briefing ---
    if ANTHROPIC_API_KEY:
        text = brief.generate(store)
        out_dir = Path(__file__).resolve().parent / "briefings"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{utcnow().date().isoformat()}.md"
        out_path.write_text(text, encoding="utf-8")
        print(f"[reasoning]  brief:   written to {out_path.relative_to(Path(__file__).resolve().parent)}")
    else:
        print("[reasoning]  brief:   no ANTHROPIC_API_KEY in .env — skipping brief")

    store.close()


if __name__ == "__main__":
    run_data_plane()
