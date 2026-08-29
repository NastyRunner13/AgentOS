"""Proposal queue. Inserts pending rows only; graph apply is GraphStore._apply."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from kernel import new_id

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


class ProposalQueue:
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

    def rejected_labels(self) -> list[str]:
        rows = self._db.execute("SELECT payload FROM proposals WHERE status = 'rejected'").fetchall()
        out = []
        for (payload,) in rows:
            data = json.loads(payload)
            out.append(str(data.get("statement") or data.get("name") or payload))
        return out

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
