"""Confirmed facts, entities, edges. INSERT only happens in _apply."""

from __future__ import annotations

import json

from kernel import new_id

# SYNC: memory-stage-gate — config/memory.yaml `stage` and AGENTARCH.md
# "STAGE 2 AUTO-CONSOLIDATE: LOCKED"
AUTO_CONSOLIDATE_UNLOCKED = False


def _score(query: str, statement: str) -> int:
    q = query.lower().split()
    body = statement.lower()
    words = set(body.split())
    n = sum(1 for t in q if t in words or (len(t) >= 4 and t in body))
    if query.lower() in body:
        n += 3
    return n


class GraphStore:
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
