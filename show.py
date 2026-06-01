"""Show everything currently stored — a quick text dashboard.

Run with:  python show.py
"""
from briefing.config import DB_PATH, TRACKED
from briefing.store import Store

appid_to_company = {}
ticker_to_company = {}
for company, cfg in TRACKED.items():
    for appid in cfg["appids"]:
        appid_to_company[appid] = company
    if cfg.get("ticker"):
        ticker_to_company[cfg["ticker"]] = company

store = Store(DB_PATH)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# --- Community: player counts ---
section("Community — Steam concurrent players")
rows = store.conn.execute(
    "SELECT entity, value FROM metrics WHERE metric='steam_ccu' ORDER BY value DESC"
).fetchall()
if not rows:
    print("  (none yet — run `python run.py`)")
for r in rows:
    name = appid_to_company.get(r["entity"], "(untracked)")
    print(f"  {name:<24}{r['entity']:<10}{int(r['value']):>10,}")

# --- Financials: stock prices ---
section("Financials — latest stock price")
rows = store.conn.execute(
    "SELECT entity, value FROM metrics WHERE metric='stock_price' ORDER BY value DESC"
).fetchall()
if not rows:
    print("  (none yet — needs a Finnhub key; foreign OTC tickers may return nothing)")
for r in rows:
    name = ticker_to_company.get(r["entity"], "(untracked)")
    print(f"  {name:<24}{r['entity']:<8}${r['value']:>10,.2f}")

# --- Financials: recent SEC filings ---
section("Financials — recent SEC filings")
docs = store.docs_for("financials")
if not docs:
    print("  (none yet)")
for d in docs[:15]:
    print(f"  {d.title}")

store.close()
