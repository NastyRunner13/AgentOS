"""L2 episodic log plus stage-1 graph. Graph writes only go through approve()."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from kernel import Bus, new_id

# SYNC: memory-stage-gate — config/memory.yaml `stage` and AGENTARCH.md
# "STAGE 2 AUTO-CONSOLIDATE: LOCKED"
AUTO_CONSOLIDATE_UNLOCKED = False

_PROPOSE_KEYS = (
    "kind",
    "statement",
    "entity_kind",
    "name",
    "attrs",
    "src",
    "rel",
    "dst",
    "supersedes",
    "about",
    "confidence",
    "source_event",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score(query: str, statement: str) -> int:
    q = query.lower().split()
    body = statement.lower()
    words = set(body.split())
    n = sum(1 for t in q if t in words or (len(t) >= 4 and t in body))
    if query.lower() in body:
        n += 3
    return n


class Episodic:
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

    def propose(self, payload: dict) -> str | None:
        raw = {k: payload[k] for k in _PROPOSE_KEYS if k in payload and payload[k] is not None}
        kind = str(raw.get("kind") or "fact")
        if kind == "preference":
            kind = "entity"
            raw["kind"] = "entity"
            raw["entity_kind"] = "Preference"
            raw.setdefault("name", raw.get("attrs", {}).get("key") if isinstance(raw.get("attrs"), dict) else "")
        raw["kind"] = kind
        if kind == "fact" and not str(raw.get("statement") or "").strip():
            return None
        if kind == "entity" and not str(raw.get("name") or "").strip():
            return None
        if kind == "edge" and not (raw.get("src") and raw.get("rel") and raw.get("dst")):
            return None
        if kind not in ("fact", "entity", "edge"):
            return None
        fingerprint = self._fingerprint(raw)
        if self._seen(fingerprint, ("approved", "rejected", "pending")):
            existing = self._pending_with(fingerprint)
            return existing
        pid = new_id()
        self._db.execute(
            "INSERT INTO proposals (id, kind, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (pid, kind, json.dumps(raw), _now()),
        )
        self._db.commit()
        if self.bus is not None:
            preview = raw.get("statement") or raw.get("name") or f"{raw.get('rel')} {raw.get('dst')}"
            self.bus.publish(
                "approval.request",
                {
                    "id": pid,
                    "action_preview": f"memory: {preview}",
                    "reason": "memory proposal",
                    "ring": 0,
                    "kind": "memory",
                    "expires_at": "",
                },
            )
        return pid

    def approve(self, ids: list[str]) -> list[str]:
        applied: list[str] = []
        now = _now()
        for pid in ids:
            row = self._db.execute(
                "SELECT id, kind, payload, status FROM proposals WHERE id = ?",
                (pid,),
            ).fetchone()
            if row is None or row[3] != "pending":
                continue
            payload = json.loads(row[2])
            self._apply(pid, str(row[1]), payload, now)
            self._db.execute(
                "UPDATE proposals SET status = 'approved', resolved_at = ? WHERE id = ?",
                (now, pid),
            )
            applied.append(pid)
            if self.bus is not None:
                self.bus.publish(
                    "approval.resolved",
                    {"id": pid, "approved": True, "expired": False, "kind": "memory"},
                )
        self._db.commit()
        return applied

    def approve_all(self) -> list[str]:
        ids = [p["id"] for p in self.pending()]
        return self.approve(ids)

    def reject(self, ids: list[str]) -> list[str]:
        done: list[str] = []
        now = _now()
        for pid in ids:
            cur = self._db.execute(
                "UPDATE proposals SET status = 'rejected', resolved_at = ? WHERE id = ? AND status = 'pending'",
                (now, pid),
            )
            if cur.rowcount:
                done.append(pid)
                if self.bus is not None:
                    self.bus.publish(
                        "approval.resolved",
                        {"id": pid, "approved": False, "expired": False, "kind": "memory"},
                    )
        self._db.commit()
        return done

    def pending(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, kind, payload, status, created_at FROM proposals WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [
            {
                "id": i,
                "kind": k,
                "payload": json.loads(p),
                "status": s,
                "created_at": ts,
            }
            for i, k, p, s, ts in rows
        ]

    def valid_facts(self) -> list[dict]:
        rows = self._db.execute(
            """
            SELECT id, statement, about, source_event, confidence, valid_from, valid_to, proposal_id
            FROM facts WHERE valid_to IS NULL ORDER BY valid_from
            """
        ).fetchall()
        return [self._fact_row(r) for r in rows]

    def recall(self, query: str = "", limit: int | None = None) -> list[dict]:
        rows = self.valid_facts()
        cap = int(limit if limit is not None else self.cfg.get("recall_limit", 8))
        if not query.strip():
            return rows[:cap]
        ranked = sorted(rows, key=lambda f: _score(query, f["statement"]), reverse=True)
        return ranked[:cap]

    def entities(self, *, valid_only: bool = True) -> list[dict]:
        sql = "SELECT id, kind, name, attrs, valid_from, valid_to FROM entities"
        if valid_only:
            sql += " WHERE valid_to IS NULL"
        rows = self._db.execute(sql).fetchall()
        return [
            {
                "id": i,
                "kind": k,
                "name": n,
                "attrs": json.loads(a or "{}"),
                "valid_from": vf,
                "valid_to": vt,
            }
            for i, k, n, a, vf, vt in rows
        ]

    def edges(self, *, valid_only: bool = True) -> list[dict]:
        sql = "SELECT id, src, rel, dst, confidence, valid_from, valid_to FROM edges"
        if valid_only:
            sql += " WHERE valid_to IS NULL"
        rows = self._db.execute(sql).fetchall()
        return [
            {"id": i, "src": s, "rel": r, "dst": d, "confidence": c, "valid_from": vf, "valid_to": vt}
            for i, s, r, d, c, vf, vt in rows
        ]

    def rejected_labels(self) -> list[str]:
        rows = self._db.execute("SELECT payload FROM proposals WHERE status = 'rejected'").fetchall()
        out = []
        for (payload,) in rows:
            data = json.loads(payload)
            out.append(str(data.get("statement") or data.get("name") or payload))
        return out

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

    def _apply(self, proposal_id: str, kind: str, payload: dict, now: str) -> None:
        conf = float(payload.get("confidence") or 1.0)
        if kind == "entity":
            eid = new_id()
            self._db.execute(
                "INSERT INTO entities (id, kind, name, attrs, valid_from) VALUES (?, ?, ?, ?, ?)",
                (
                    eid,
                    str(payload.get("entity_kind") or "Person"),
                    str(payload.get("name") or ""),
                    json.dumps(payload.get("attrs") or {}),
                    now,
                ),
            )
            return
        if kind == "edge":
            self._db.execute(
                "INSERT INTO edges (id, src, rel, dst, confidence, valid_from) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), str(payload["src"]), str(payload["rel"]), str(payload["dst"]), conf, now),
            )
            return
        fid = new_id()
        about = payload.get("about")
        src_ev = payload.get("source_event")
        self._db.execute(
            """
            INSERT INTO facts (id, statement, about, source_event, confidence, valid_from, proposal_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fid,
                str(payload.get("statement") or ""),
                str(about) if about else None,
                int(src_ev) if src_ev is not None else None,
                conf,
                now,
                proposal_id,
            ),
        )
        if about:
            self._db.execute(
                "INSERT INTO edges (id, src, rel, dst, confidence, valid_from) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), fid, "ABOUT", str(about), conf, now),
            )
        old = payload.get("supersedes")
        if old:
            self._db.execute("UPDATE facts SET valid_to = ? WHERE id = ? AND valid_to IS NULL", (now, str(old)))
            self._db.execute(
                "INSERT INTO edges (id, src, rel, dst, confidence, valid_from) VALUES (?, ?, ?, ?, ?, ?)",
                (new_id(), fid, "SUPERSEDES", str(old), conf, now),
            )

    def _fingerprint(self, payload: dict) -> str:
        kind = payload.get("kind")
        if kind == "fact":
            return "fact:" + str(payload.get("statement") or "").strip().lower()
        if kind == "entity":
            return "entity:" + str(payload.get("entity_kind") or "") + ":" + str(payload.get("name") or "").strip().lower()
        return "edge:" + f"{payload.get('src')}|{payload.get('rel')}|{payload.get('dst')}"

    def _seen(self, fingerprint: str, statuses: tuple[str, ...]) -> bool:
        q = ",".join("?" * len(statuses))
        rows = self._db.execute(
            f"SELECT payload, status FROM proposals WHERE status IN ({q})",
            statuses,
        ).fetchall()
        for payload, _status in rows:
            if self._fingerprint(json.loads(payload)) == fingerprint:
                return True
        if "approved" in statuses:
            if fingerprint.startswith("fact:"):
                stmt = fingerprint[5:]
                (n,) = self._db.execute(
                    "SELECT COUNT(*) FROM facts WHERE lower(statement) = ? AND valid_to IS NULL",
                    (stmt,),
                ).fetchone()
                if n:
                    return True
        return False

    def _pending_with(self, fingerprint: str) -> str | None:
        rows = self._db.execute(
            "SELECT id, payload FROM proposals WHERE status = 'pending'"
        ).fetchall()
        for pid, payload in rows:
            if self._fingerprint(json.loads(payload)) == fingerprint:
                return str(pid)
        return None

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

    def _fact_row(self, row: tuple) -> dict:
        id_, statement, about, source_event, confidence, valid_from, valid_to, proposal_id = row
        return {
            "id": id_,
            "statement": statement,
            "about": about,
            "source_event": source_event,
            "confidence": confidence,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "proposal_id": proposal_id,
        }
