"""SQLite storage for ingestion metadata, ambient flags, and repo status.

Kept deliberately simple (stdlib sqlite3, no ORM) — this is bookkeeping,
not the semantic search path, which lives in retrieval/store.py.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from lore.config import settings
from lore.ingestion.github_ingest import HistoryItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS history_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_status (
    repo TEXT PRIMARY KEY,
    indexed_chunks INTEGER NOT NULL,
    last_ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    message TEXT NOT NULL,
    citations_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at TEXT NOT NULL
);
"""


@dataclass
class Flag:
    id: int
    repo: str
    file_path: str
    message: str
    citations: list[dict]
    confidence: float
    created_at: str


class Database:
    def __init__(self):
        self.path = settings.db_path
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_history_item(self, item: HistoryItem) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO history_items (id, kind, title, author, url, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url""",
                (item.id, item.kind, item.title, item.author, item.url, item.created_at.isoformat()),
            )

    def set_repo_status(self, repo: str, indexed_chunks: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO repo_status (repo, indexed_chunks, last_ingested_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(repo) DO UPDATE SET indexed_chunks=excluded.indexed_chunks,
                       last_ingested_at=excluded.last_ingested_at""",
                (repo, indexed_chunks, datetime.now(timezone.utc).isoformat()),
            )

    def get_repo_status(self, repo: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM repo_status WHERE repo = ?", (repo,)).fetchone()
            return dict(row) if row else None

    def add_flag(self, repo: str, file_path: str, message: str, citations: list[dict], confidence: float) -> Flag:
        import json

        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO flags (repo, file_path, message, citations_json, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (repo, file_path, message, json.dumps(citations), confidence, datetime.now(timezone.utc).isoformat()),
            )
            row = conn.execute("SELECT * FROM flags WHERE id = ?", (cur.lastrowid,)).fetchone()
            return _row_to_flag(row)

    def recent_flags(self, repo: str | None = None, limit: int = 50) -> list[Flag]:
        with self._connect() as conn:
            if repo:
                rows = conn.execute(
                    "SELECT * FROM flags WHERE repo = ? ORDER BY id DESC LIMIT ?", (repo, limit)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM flags ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [_row_to_flag(r) for r in rows]


def _row_to_flag(row: sqlite3.Row) -> Flag:
    import json

    return Flag(
        id=row["id"],
        repo=row["repo"],
        file_path=row["file_path"],
        message=row["message"],
        citations=json.loads(row["citations_json"]),
        confidence=row["confidence"],
        created_at=row["created_at"],
    )
