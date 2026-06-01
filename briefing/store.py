"""SQLite persistence layer.

The database file lives at data/briefing.db and is COMMITTED TO THE REPO (not
gitignored). That is deliberate: the git history of this file IS the time-series
dataset. Every scheduled run appends the day's points and commits, so the commit
log doubles as timestamped proof the pipeline has been running daily — and you
get a growing dataset with zero external infrastructure.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Doc, Metric

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    section      TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    body         TEXT,
    published_at TEXT,
    fetched_at   TEXT NOT NULL,
    entities     TEXT,            -- JSON array
    extra        TEXT             -- JSON object
);

CREATE TABLE IF NOT EXISTS metrics (
    id          TEXT PRIMARY KEY,
    metric      TEXT NOT NULL,
    entity      TEXT NOT NULL,
    value       REAL NOT NULL,
    source      TEXT NOT NULL,
    observed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_series ON metrics(metric, entity, observed_at);
CREATE INDEX IF NOT EXISTS idx_docs_section   ON docs(section, fetched_at);
"""


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def init(self) -> None:
        """Create tables and indexes if they don't exist. Safe to call every run."""
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---- writes (idempotent via INSERT OR REPLACE on the deterministic id) ----

    def upsert_metrics(self, metrics: list[Metric]) -> int:
        rows = [
            (m.id, m.metric, m.entity, m.value, m.source, m.observed_at.isoformat())
            for m in metrics
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO metrics "
            "(id, metric, entity, value, source, observed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def upsert_docs(self, docs: list[Doc]) -> int:
        rows = [
            (
                d.id, d.source, d.section, d.title, d.url, d.body,
                d.published_at.isoformat() if d.published_at else None,
                d.fetched_at.isoformat(),
                json.dumps(d.entities),
                json.dumps(d.extra),
            )
            for d in docs
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO docs "
            "(id, source, section, title, url, body, published_at, fetched_at, entities, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    # ---- reads (return dataclasses so the reasoning plane stays typed) ----

    def metrics_for(
        self, metric: str, entity: str, since: datetime | None = None
    ) -> list[Metric]:
        sql = "SELECT * FROM metrics WHERE metric = ? AND entity = ?"
        args: list = [metric, entity]
        if since:
            sql += " AND observed_at >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY observed_at ASC"
        return [
            Metric(
                id=r["id"], metric=r["metric"], entity=r["entity"],
                value=r["value"], source=r["source"],
                observed_at=_parse_dt(r["observed_at"]),
            )
            for r in self.conn.execute(sql, args)
        ]

    def docs_for(self, section: str, since: datetime | None = None) -> list[Doc]:
        sql = "SELECT * FROM docs WHERE section = ?"
        args: list = [section]
        if since:
            sql += " AND fetched_at >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY fetched_at DESC"
        return [
            Doc(
                id=r["id"], source=r["source"], section=r["section"],
                title=r["title"], url=r["url"], body=r["body"],
                published_at=_parse_dt(r["published_at"]),
                fetched_at=_parse_dt(r["fetched_at"]),
                entities=json.loads(r["entities"] or "[]"),
                extra=json.loads(r["extra"] or "{}"),
            )
            for r in self.conn.execute(sql, args)
        ]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
