"""
SQLite-backed state management for resumable FRED ingest.

The state DB acts as a local mirror of all fetched FRED metadata.
Once series JSON is stored here, filtering and embedding can be
re-run without touching the FRED API again.

Schema
------
releases    — one row per FRED release; status tracks fetch progress
categories  — one row per visited category node in the tree walk
series      — one row per unique series; INSERT OR IGNORE deduplicates
ingest_runs — audit log of each ingest execution
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    notes       TEXT    -- free-form context (e.g. "full rebuild", "resume")
);

CREATE TABLE IF NOT EXISTS releases (
    release_id   INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'pending',   -- pending | done | error
    series_count INTEGER DEFAULT 0,
    fetched_at   TEXT,
    error_msg    TEXT
);

CREATE TABLE IF NOT EXISTS categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    parent_id   INTEGER,
    status      TEXT    NOT NULL DEFAULT 'pending',    -- pending | done | error
    fetched_at  TEXT,
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS series (
    series_id    TEXT PRIMARY KEY,
    raw_json     TEXT NOT NULL,       -- full API response JSON blob
    first_source TEXT,                -- "release:<id>" or "category:<id>"
    discovered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS series_tags (
    series_id TEXT NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (series_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_series_tags_series ON series_tags(series_id);
"""


class IngestState:
    """
    Manages ingest progress in a local SQLite database.

    Thread safety: not thread-safe; designed for single-process sequential use.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Run tracking
    # ------------------------------------------------------------------

    def start_run(self, notes: str = "") -> int:
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT INTO ingest_runs (started_at, notes) VALUES (?, ?)",
            (now, notes),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def finish_run(self, run_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE ingest_runs SET finished_at = ? WHERE run_id = ?",
            (now, run_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Release management
    # ------------------------------------------------------------------

    def register_releases(self, releases: list[dict[str, Any]]) -> int:
        """Insert new releases; skip any already registered. Returns count inserted."""
        rows = [(r["id"], r["name"]) for r in releases]
        self._conn.executemany(
            "INSERT OR IGNORE INTO releases (release_id, name) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()
        count = self._conn.execute(
            "SELECT changes()"
        ).fetchone()[0]
        return count

    def get_pending_releases(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT release_id, name FROM releases WHERE status = 'pending' ORDER BY release_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_release_done(self, release_id: int, series_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """UPDATE releases
               SET status = 'done', series_count = ?, fetched_at = ?
               WHERE release_id = ?""",
            (series_count, now, release_id),
        )
        self._conn.commit()

    def mark_release_error(self, release_id: int, error_msg: str) -> None:
        self._conn.execute(
            "UPDATE releases SET status = 'error', error_msg = ? WHERE release_id = ?",
            (error_msg[:1000], release_id),
        )
        self._conn.commit()

    def release_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM releases GROUP BY status"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Category management
    # ------------------------------------------------------------------

    def register_category(self, category_id: int, name: str, parent_id: int | None) -> bool:
        """Register a category node. Returns True if newly inserted."""
        self._conn.execute(
            "INSERT OR IGNORE INTO categories (category_id, name, parent_id) VALUES (?, ?, ?)",
            (category_id, name, parent_id),
        )
        self._conn.commit()
        return self._conn.execute("SELECT changes()").fetchone()[0] == 1

    def is_category_done(self, category_id: int) -> bool:
        row = self._conn.execute(
            "SELECT status FROM categories WHERE category_id = ?",
            (category_id,),
        ).fetchone()
        return row is not None and row["status"] == "done"

    def mark_category_done(self, category_id: int, series_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """UPDATE categories
               SET status = 'done', fetched_at = ?
               WHERE category_id = ?""",
            (now, category_id),
        )
        self._conn.commit()

    def mark_category_error(self, category_id: int, error_msg: str) -> None:
        self._conn.execute(
            "UPDATE categories SET status = 'error', error_msg = ? WHERE category_id = ?",
            (error_msg[:1000], category_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Series storage
    # ------------------------------------------------------------------

    def store_series_batch(
        self, series_list: list[dict[str, Any]], source: str
    ) -> int:
        """
        Persist a batch of raw series dicts.

        Uses INSERT OR IGNORE so the first discovery wins; later encounters
        (same series in a different release) are silently skipped.
        Returns the number of newly inserted series.
        """
        rows = [
            (s["id"], json.dumps(s), source)
            for s in series_list
            if "id" in s
        ]
        self._conn.executemany(
            "INSERT OR IGNORE INTO series (series_id, raw_json, first_source) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()
        return self._conn.execute("SELECT changes()").fetchone()[0]

    def store_tags_batch(self, series_id: str, tags: list[str]) -> None:
        rows = [(series_id, t) for t in tags]
        self._conn.executemany(
            "INSERT OR IGNORE INTO series_tags (series_id, tag) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()

    def iter_all_series(self) -> Iterator[tuple[dict[str, Any], list[str]]]:
        """
        Yield (raw_series_dict, tags) for every stored series.

        Streams from SQLite in batches to avoid loading 840K rows at once.
        """
        page_size = 5000
        offset = 0
        while True:
            rows = self._conn.execute(
                "SELECT series_id, raw_json FROM series LIMIT ? OFFSET ?",
                (page_size, offset),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                raw = json.loads(row["raw_json"])
                # Fetch tags for this series
                tag_rows = self._conn.execute(
                    "SELECT tag FROM series_tags WHERE series_id = ?",
                    (row["series_id"],),
                ).fetchall()
                tags = [t["tag"] for t in tag_rows]
                yield raw, tags
            offset += page_size

    def total_series_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM series").fetchone()[0]

    def series_exists(self, series_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM series WHERE series_id = ?", (series_id,)
            ).fetchone()
            is not None
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        release_counts = self.release_counts()
        category_counts = dict(
            self._conn.execute(
                "SELECT status, COUNT(*) FROM categories GROUP BY status"
            ).fetchall()
        )
        return {
            "releases": release_counts,
            "categories": category_counts,
            "total_series": self.total_series_count(),
        }

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "IngestState":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
