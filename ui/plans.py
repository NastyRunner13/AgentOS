"""Saved Architect plans. Not L2; never recalled as facts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kernel.bus import new_id

PLAN_APPROVE = "__plan_approve__"
PLAN_CHANGES = "__plan_changes__"
PLAN_COMMENT = "__plan_comment__"
PLAN_QUIT = "__plan_quit__"

WAITING = "waiting_approval"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def title_from_body(body: str) -> str:
    for line in (body or "").splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            return text[:48]
    return "untitled plan"


@dataclass
class Plan:
    id: str
    title: str
    status: str
    session_id: str
    body: str
    created_at: str = ""
    updated_at: str = ""
    comments: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Plan:
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            status=str(data.get("status") or WAITING),
            session_id=str(data.get("session_id") or ""),
            body=str(data.get("body") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            comments=list(data.get("comments") or []),
        )


class PlanStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, plan_id: str) -> Path:
        return self.dir / f"{plan_id}.json"

    def save(self, plan: Plan) -> None:
        plan.updated_at = _now()
        if not plan.created_at:
            plan.created_at = plan.updated_at
        self._path(plan.id).write_text(json.dumps(plan.as_dict(), indent=2), encoding="utf-8")

    def get(self, prefix: str) -> Plan:
        needle = prefix.strip()
        if not needle:
            raise KeyError("missing plan id")
        matches = [p for p in self.dir.glob("*.json") if p.stem == needle or p.stem.startswith(needle)]
        if not matches:
            raise KeyError(f"no plan matching {needle!r}")
        if len(matches) > 1 and not any(p.stem == needle for p in matches):
            ids = ", ".join(p.stem for p in matches[:6])
            raise KeyError(f"ambiguous plan id {needle!r}: {ids}")
        path = next((p for p in matches if p.stem == needle), matches[0])
        return Plan.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, session_id: str = "", limit: int = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for path in self.dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            if session_id and str(data.get("session_id") or "") != session_id:
                continue
            rows.append(
                {
                    "id": data.get("id", path.stem),
                    "title": data.get("title") or "",
                    "status": data.get("status") or "",
                    "session_id": data.get("session_id") or "",
                    "updated_at": data.get("updated_at") or data.get("created_at") or "",
                }
            )
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows[:limit]

    def latest_for(self, session_id: str) -> Plan | None:
        rows = self.list(session_id=session_id, limit=1)
        if not rows:
            return None
        try:
            return self.get(str(rows[0]["id"]))
        except (KeyError, OSError, json.JSONDecodeError):
            return None

    def waiting_for(self, session_id: str) -> Plan | None:
        for row in self.list(session_id=session_id, limit=50):
            if row.get("status") == WAITING:
                try:
                    return self.get(str(row["id"]))
                except (KeyError, OSError, json.JSONDecodeError):
                    continue
        return None

    def upsert_waiting(self, session_id: str, body: str, title: str = "") -> Plan:
        title = title or title_from_body(body)
        current = self.waiting_for(session_id) or self.latest_for(session_id)
        if current and current.status in (WAITING, "changes_requested", "drafting"):
            current.body = body
            current.title = title
            current.status = WAITING
            self.save(current)
            return current
        plan = Plan(
            id=new_id(),
            title=title,
            status=WAITING,
            session_id=session_id,
            body=body,
        )
        self.save(plan)
        return plan

    def set_status(self, plan_id: str, status: str, comment: str = "") -> Plan:
        plan = self.get(plan_id)
        plan.status = status
        if comment:
            plan.comments.append(comment)
        self.save(plan)
        return plan


def plan_action(line: str, *, waiting: bool, collecting: str = "") -> tuple[str, str]:
    """Map a composer line to a plan action. Commands are stripped before this."""
    if not waiting:
        return ("none", line)
    raw = (line or "").strip()
    if collecting:
        return (collecting, raw)
    if raw in ("a", PLAN_APPROVE):
        return ("approve", "")
    if raw in ("q", PLAN_QUIT):
        return ("quit", "")
    if raw in ("s", PLAN_CHANGES):
        return ("ask_changes", "")
    if raw in ("c", PLAN_COMMENT):
        return ("ask_comment", "")
    if not raw:
        return ("none", "")
    return ("comment", raw)


def updated_plan_body(mode: str, path: Path, before: str | None) -> str | None:
    """Return plan.md text when Architect just wrote or changed it."""
    if (mode or "").lower() != "architect":
        return None
    if not path.is_file():
        return None
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not body.strip():
        return None
    if before is not None and body == before:
        return None
    return body


def execute_prompt(plan: Plan) -> str:
    return (
        "Execute the approved plan. Follow the steps. Do not rewrite the plan "
        "unless you are stuck.\n\n"
        f"{plan.body}"
    )


def revise_prompt(feedback: str, kind: str = "comment") -> str:
    label = "Change request" if kind == "changes" else "Comment"
    return (
        f"{label} on the plan. Update plan.md in place. Do not implement.\n\n"
        f"{feedback}"
    )
