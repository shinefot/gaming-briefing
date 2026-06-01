"""SEC EDGAR fetcher — lane 1a (Market & Financials: official filings).

Free, no API key. SEC just asks for a descriptive User-Agent with contact info
on every request (set SEC_USER_AGENT in .env). We map each tracked ticker to
its CIK (SEC's internal company id), pull recent filings, and keep the material
forms: 8-K (material events), 10-Q / 10-K (quarterly / annual), and 20-F / 6-K
(foreign issuers). Each kept filing becomes a Doc in the 'financials' section.
"""
from __future__ import annotations

from datetime import date, timedelta

import requests

from ..config import SEC_FORMS, SEC_LOOKBACK_DAYS, SEC_USER_AGENT
from ..models import Doc

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _headers() -> dict:
    return {"User-Agent": SEC_USER_AGENT}


def ticker_cik_map(session=None) -> dict[str, int]:
    """Return {TICKER: cik_int} from SEC's master company list."""
    http = session or requests
    resp = http.get(TICKER_MAP_URL, headers=_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}


def filings_for(cik: int, ticker: str, since: str, session=None) -> list[Doc]:
    """Recent material filings for one company filed on/after the ISO date `since`."""
    http = session or requests
    resp = http.get(SUBMISSIONS_URL.format(cik=cik), headers=_headers(), timeout=30)
    resp.raise_for_status()
    recent = resp.json().get("filings", {}).get("recent", {})

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    primary = recent.get("primaryDocument", [])
    descs = recent.get("primaryDocDescription", [""] * len(forms))

    docs: list[Doc] = []
    for form, fdate, accn, pdoc, desc in zip(forms, dates, accns, primary, descs):
        if form not in SEC_FORMS or fdate < since:
            continue
        # Build the direct link to the filing document.
        accn_nodash = accn.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/{pdoc}"
        docs.append(Doc(
            source="sec_edgar",
            section="financials",
            title=f"{ticker} filed {form} on {fdate}",
            url=url,
            body=desc or "",
            entities=[ticker],
            extra={"form": form, "filing_date": fdate, "cik": cik},
        ))
    return docs


def fetch(tracked: dict, session=None) -> list[Doc]:
    """Pull material filings for every tracked ticker that exists in EDGAR.

    Graceful: a ticker not in EDGAR (common for foreign OTC tickers) or a
    failed request is logged and skipped — the rest of the run continues.
    """
    since = (date.today() - timedelta(days=SEC_LOOKBACK_DAYS)).isoformat()
    try:
        cik_map = ticker_cik_map(session=session)
    except Exception as exc:  # noqa: BLE001
        print(f"[sec] could not load ticker->CIK map: {exc}")
        return []

    docs: list[Doc] = []
    for company, cfg in tracked.items():
        ticker = (cfg.get("ticker") or "").upper()
        cik = cik_map.get(ticker)
        if not cik:
            print(f"[sec] {company} ({ticker}) not found in EDGAR — skipped")
            continue
        try:
            docs.extend(filings_for(cik, ticker, since, session=session))
        except Exception as exc:  # noqa: BLE001
            print(f"[sec] {ticker} filings failed: {exc}")
            continue
    return docs
