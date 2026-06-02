"""Static configuration, secrets loading, and the tracked-entities table.

The .env loader near the top makes your secrets (the Finnhub key) available to
the code without ever committing them. The TRACKED dict is the join key the
whole system relies on: company -> ticker (for filings + prices) and appids
(for player counts).
"""
import os
from pathlib import Path


def _load_env() -> None:
    """Read .env (if present) into the environment.

    A tiny hand-rolled loader so we need no extra dependency. We use
    setdefault so that REAL environment variables (e.g. GitHub Actions
    secrets, later) always win over the local .env file.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


_load_env()

# --- secrets / settings (populated from .env above) ---
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Haiku is the cheap, fast model — right for summarizing structured data.
BRIEF_MODEL = os.environ.get("BRIEF_MODEL", "claude-haiku-4-5-20251001")
# SEC asks for a descriptive User-Agent with contact info on every request.
# Put your own email in .env as SEC_USER_AGENT to be a good citizen.
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "gaming-briefing (portfolio project) you@example.com"
)
# Which filing forms count as material, and how far back to scan each run.
SEC_FORMS = {"8-K", "10-Q", "10-K", "20-F", "6-K"}
SEC_LOOKBACK_DAYS = 30

# Repo-relative path. The DB is committed here (see store.py docstring).
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "briefing.db"

# company -> {ticker, appids}
TRACKED: dict[str, dict] = {
    "Take-Two Interactive": {"ticker": "TTWO", "appids": ["1174180"]},
    "Electronic Arts":      {"ticker": "EA",   "appids": ["1237970"]},
    "Ubisoft":              {"ticker": "UBSFY","appids": ["2208920"]},
    "CD Projekt":           {"ticker": "OTGLY","appids": ["1091500"]},
    "Capcom":               {"ticker": "CCOEY","appids": ["1446780"]},
    "Square Enix":          {"ticker": "SQNXF","appids": ["1462040"]},
    "Sega / Atlus":         {"ticker": "SGAMY","appids": ["1245620"]},
    "Paradox Interactive":  {"ticker": "PRXF", "appids": ["281990"]},
    "Embracer Group":       {"ticker": "THQQF","appids": ["553850"]},
    "Roblox":               {"ticker": "RBLX", "appids": []},
    "Microsoft":            {"ticker": "MSFT", "appids": []},
    "Sony":                 {"ticker": "SONY", "appids": ["1593500"]},
}


def all_appids() -> list[str]:
    """Flat list of every tracked Steam appid, for the poller."""
    return [appid for cfg in TRACKED.values() for appid in cfg["appids"]]


def all_tickers() -> list[str]:
    """Flat list of every tracked ticker, for the financials fetchers."""
    return [cfg["ticker"] for cfg in TRACKED.values() if cfg.get("ticker")]
