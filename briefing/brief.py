"""The reasoning plane: turn stored facts into a written briefing.

Design principle that makes this trustworthy: the LLM NEVER invents numbers.
We read exact figures from the database in plain code, format them into a
factual block, and the model's only job is to write readable prose AROUND facts
it has been handed. It phrases; it does not recall. That's the whole guardrail.

The actual Anthropic call is isolated in `_call_claude` and injectable, so the
test suite runs offline and free with a fake writer.
"""
from __future__ import annotations

from datetime import timedelta

from .config import ANTHROPIC_API_KEY, BRIEF_MODEL, TRACKED
from .models import utcnow
from .store import Store

# Lookups so the brief shows readable names, not bare ids.
_APPID_TO_COMPANY = {a: c for c, cfg in TRACKED.items() for a in cfg["appids"]}
_TICKER_TO_COMPANY = {cfg["ticker"]: c for c, cfg in TRACKED.items() if cfg.get("ticker")}


def gather_facts(store: Store) -> str:
    """Pull today's data from the store into a plain-text factual block.

    This is pure deterministic code — no LLM. The block we return is the
    ground truth the model is allowed to write about, and nothing else.
    """
    lines: list[str] = []
    week_ago = utcnow() - timedelta(days=7)

    # --- Community: player counts, with a week-over-week trend if we have it ---
    lines.append("## Steam concurrent players (current)")
    ccu_rows = store.conn.execute(
        "SELECT entity, value FROM metrics WHERE metric='steam_ccu' "
        "AND observed_at >= ? ORDER BY value DESC",
        ((utcnow() - timedelta(hours=36)).isoformat(),),
    ).fetchall()
    for r in ccu_rows:
        name = _APPID_TO_COMPANY.get(r["entity"], r["entity"])
        # trend: compare to the oldest point in the last 7 days for this game
        hist = store.metrics_for("steam_ccu", r["entity"], since=week_ago)
        trend = ""
        if len(hist) >= 2 and hist[0].value:
            pct = (hist[-1].value - hist[0].value) / hist[0].value * 100
            trend = f" ({pct:+.0f}% over {len(hist)} days)"
        lines.append(f"- {name}: {int(r['value']):,} players{trend}")

    # --- Financials: latest stock prices ---
    lines.append("\n## Latest stock prices")
    price_rows = store.conn.execute(
        "SELECT entity, value FROM metrics WHERE metric='stock_price' "
        "AND observed_at >= ? ORDER BY value DESC",
        ((utcnow() - timedelta(hours=36)).isoformat(),),
    ).fetchall()
    for r in price_rows:
        name = _TICKER_TO_COMPANY.get(r["entity"], r["entity"])
        lines.append(f"- {name} ({r['entity']}): ${r['value']:,.2f}")

    # --- Financials: recent SEC filings (last 14 days) ---
    lines.append("\n## Recent SEC filings (last 14 days)")
    docs = store.docs_for("financials", since=utcnow() - timedelta(days=14))
    if not docs:
        lines.append("- (none in this window)")
    for d in docs:
        form = d.extra.get("form", "filing")
        fdate = d.extra.get("filing_date", "")
        company = _TICKER_TO_COMPANY.get(d.entities[0] if d.entities else "", "")
        label = f"{company} " if company else ""
        lines.append(f"- {label}{d.entities[0] if d.entities else ''} {form} ({fdate})")

    return "\n".join(lines)


SYSTEM_PROMPT = """You are writing a daily gaming-industry briefing for a busy \
executive or investor who will SCAN it in under a minute.

You will be given a block of FACTS — current player counts, stock prices, and \
recent regulatory filings for major gaming companies. Write a tight briefing in \
Markdown with exactly three sections: Market & Financials, Community & Engagement, \
and Regulatory Filings.

Format:
- Open with a single bold one-line headline (the day's most notable item).
- Each section: 2–3 short sentences OR a few bullet points. No long paragraphs.
- Lead each section with what stands out, not a recap of every figure.
- Total length: aim for under 200 words across all three sections.

Critical rules:
- Use ONLY the numbers and facts provided. Never invent or estimate figures.
- State facts and flag what's notable. Do NOT speculate about CAUSES — ban the \
words "suggesting", "suggests", "likely", "may reflect", "indicating", "reflects". \
You have one daily snapshot; you cannot know WHY a number is what it is. If you \
catch yourself explaining a cause, delete that clause.
- Do NOT use comparative/superlative claims the data can't support. You have only \
today's values and (where given) a short trend. You do NOT have historical context, \
so never write "historic low", "all-time", "record", "unprecedented", or similar. \
"Lowest in this list" is allowed (it's true of the data); "historic low" is not.
- Compare values only WITHIN the provided data ("lowest among the tracked \
companies"), never against outside knowledge.
- Where a trend percentage is given, lead with it — that's the most valuable signal.
- No investment advice, no predictions.
- If a section has little of note, say so briefly rather than padding."""


def _call_claude(facts: str, api_key: str, model: str) -> str:
    """The actual Anthropic API call. Isolated so tests can replace it."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=1200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Here are today's facts:\n\n{facts}"}],
    )
    return "".join(block.text for block in msg.content if block.type == "text")


def generate(store: Store, writer=None, api_key: str = "", model: str = "") -> str:
    """Produce the full briefing text. `writer` is injectable for testing.

    `writer` is a function (facts) -> str. By default it calls Claude; tests
    pass a fake so no network or key is needed.
    """
    facts = gather_facts(store)
    key = api_key or ANTHROPIC_API_KEY
    mdl = model or BRIEF_MODEL

    if writer is None:
        if not key:
            raise RuntimeError("No ANTHROPIC_API_KEY set — cannot write the brief.")
        writer = lambda f: _call_claude(f, key, mdl)  # noqa: E731

    body = writer(facts)
    date_str = utcnow().date().isoformat()
    return f"# Gaming Industry Briefing — {date_str}\n\n{body}\n"
