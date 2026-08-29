"""L2 episodic log. Schema for the whole SQLite file lives here; graph writes do not."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from kernel import Bus
from memory.graph import GraphStore
from memory.proposals import ProposalQueue


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Episodic(ProposalQueue, GraphStore):
    def __init__(self, db_path: Path, cfg: dict | None = None, bus: Bus | None = None) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cfg = dict(cfg or {})
        self.bus = bus
        self._librarian_fails = 0
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                role TEXT,
                content TEXT,
                meta TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                content,
                content=events,
                content_rowid=id
            );
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                attrs TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT
            );
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                statement TEXT NOT NULL,
                about TEXT,
                source_event INTEGER,
                confidence REAL NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT,
                proposal_id TEXT
            );
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                src TEXT NOT NULL,
                rel TEXT NOT NULL,
                dst TEXT NOT NULL,
                confidence REAL NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            """
        )
        self._db.commit()

    @property
    def stage(self) -> int:
        return int(self.cfg.get("stage", 1))

    def write(
        self,
        kind: str,
        content: str = "",
        role: str | None = None,
        meta: dict | None = None,
    ) -> int:
        ts = _now()
        cur = self._db.execute(
            "INSERT INTO events (ts, kind, role, content, meta) VALUES (?, ?, ?, ?, ?)",
            (ts, kind, role, content, json.dumps(meta or {})),
        )
        rowid = int(cur.lastrowid)
        self._db.execute(
            "INSERT INTO events_fts (rowid, content) VALUES (?, ?)",
            (rowid, content or ""),
        )
        self._db.commit()
        return rowid

    def count(self) -> int:
        (n,) = self._db.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(n)

    def latest(self, n: int = 20) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, ts, kind, role, content, meta FROM events ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
        return [self._event_row(r) for r in reversed(rows)]

    def search(self, query: str, n: int = 20) -> list[dict]:
        q = query.strip()
        if not q:
            return []
        try:
            rows = self._db.execute(
                """
                SELECT e.id, e.ts, e.kind, e.role, e.content, e.meta
                FROM events_fts
                JOIN events e ON e.id = events_fts.rowid
                WHERE events_fts MATCH ?
                LIMIT ?
                """,
                (q, n),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = self._db.execute(
                """
                SELECT id, ts, kind, role, content, meta FROM events
                WHERE content LIKE ? ORDER BY id DESC LIMIT ?
                """,
                (f"%{q}%", n),
            ).fetchall()
        return [self._event_row(r) for r in rows]

    def librarian_fail(self) -> int:
        self._librarian_fails += 1
        return self._librarian_fails

    def librarian_ok(self) -> None:
        self._librarian_fails = 0

    @property
    def librarian_stuck(self) -> bool:
        return self._librarian_fails >= int(self.cfg.get("librarian_fail_stuck", 2))

    def close(self) -> None:
        self._db.close()

    def _event_row(self, row: tuple) -> dict:
        id_, ts, kind, role, content, meta = row
        return {
            "id": id_,
            "ts": ts,
            "kind": kind,
            "role": role,
            "content": content,
            "meta": json.loads(meta or "{}"),
        }
