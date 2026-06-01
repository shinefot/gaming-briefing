"""The normalized data model — the shared spine of the pipeline.

Every fetcher, regardless of source (SEC, Steam, RSS, ...), maps its output
into one of these two record types. The reasoning plane then operates ONLY on
Doc and Metric and never needs to know where a fact came from. That decoupling
is the whole reason the normalizer step exists: add a new source later and the
reasoning code doesn't change.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Timezone-aware UTC now. Always use this, never naive datetimes."""
    return datetime.now(timezone.utc)


def make_id(*parts: str) -> str:
    """Stable short id from arbitrary parts. Used as the dedup key.

    Deterministic: the same inputs always produce the same id, which is what
    lets us use INSERT OR REPLACE for idempotent writes.
    """
    joined = "|".join(p.strip() for p in parts if p)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


@dataclass
class Doc:
    """Any text-bearing thing that 'happened' — a filing, an article, a release."""

    source: str                       # "sec_edgar" | "ign_rss" | "tavily" | ...
    section: str                      # "financials" | "community" | "releases"
    title: str
    url: str
    body: str = ""                    # cleaned text or summary
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=utcnow)
    entities: list[str] = field(default_factory=list)   # tickers, appids, names
    extra: dict = field(default_factory=dict)           # source-specific payload
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            # Dedup on source + url (falling back to title) so the same article
            # pulled twice in one run collapses to a single row.
            self.id = make_id(self.source, self.url or self.title)


@dataclass
class Metric:
    """Any time-series observation — a player count, a closing price."""

    metric: str                       # "steam_ccu" | "stock_close"
    entity: str                       # appid "1245620" or ticker "TTWO"
    value: float
    source: str
    observed_at: datetime = field(default_factory=utcnow)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            # Key on metric + entity + DAY. Running the workflow twice in one day
            # then upserts the same row (last write wins) instead of creating a
            # duplicate point. For a once-daily free-tier run this gives exactly
            # one clean point per game per day.
            day = self.observed_at.date().isoformat()
            self.id = make_id(self.metric, self.entity, day)
