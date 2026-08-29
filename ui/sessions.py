"""CLI conversation files. L2 stays the audit log; these are Master.history only."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kernel.bus import new_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _title_from_history(history: list[dict[str, Any]]) -> str:
    for msg in history:
        if msg.get("role") == "user":
            text = " ".join(str(msg.get("content") or "").split())
            if text:
                return text[:48]
    return ""


class SessionStore:
    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self.id = new_id()
        self.title = ""
        self.mode = "Code"
        self.created_at = _now()
        self.updated_at = self.created_at
        self.history: list[dict[str, Any]] = []

    def create(self, mode: str = "Code") -> None:
        self.id = new_id()
        self.title = ""
        self.mode = mode
        self.created_at = _now()
        self.updated_at = self.created_at
        self.history = []

    def save(self, history: list[dict[str, Any]], mode: str | None = None) -> None:
        self.history = list(history)
        if mode is not None:
            self.mode = mode
        if not self.title:
            self.title = _title_from_history(self.history)
        if not self.history:
            return
        self.updated_at = _now()
        payload = {
            "id": self.id,
            "title": self.title,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": self.history,
        }
        path = self.dir / f"{self.id}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = []
        for path in self.dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or not data.get("id"):
                continue
            rows.append(
                {
                    "id": data.get("id", path.stem),
                    "title": data.get("title") or "",
                    "mode": data.get("mode") or "Code",
                    "created_at": data.get("created_at") or "",
                    "updated_at": data.get("updated_at") or data.get("created_at") or "",
                    "turns": len(data.get("history") or []),
                }
            )
        rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
        return rows[:limit]

    def load(self, prefix: str) -> dict[str, Any]:
        needle = prefix.strip()
        if not needle:
            raise KeyError("missing session id")
        matches = []
        for path in self.dir.glob("*.json"):
            if path.stem.startswith(needle) or needle == path.stem:
                matches.append(path)
        if not matches:
            raise KeyError(f"no session matching {needle!r}")
        if len(matches) > 1 and not any(p.stem == needle for p in matches):
            ids = ", ".join(p.stem for p in matches[:6])
            raise KeyError(f"ambiguous session id {needle!r}: {ids}")
        path = next((p for p in matches if p.stem == needle), matches[0])
        data = json.loads(path.read_text(encoding="utf-8"))
        self.id = str(data.get("id") or path.stem)
        self.title = str(data.get("title") or "")
        self.mode = str(data.get("mode") or "Code")
        self.created_at = str(data.get("created_at") or _now())
        self.updated_at = str(data.get("updated_at") or self.created_at)
        self.history = list(data.get("history") or [])
        return data

    def rename(self, title: str) -> None:
        self.title = " ".join(title.split())
        if self.history:
            self.save(self.history, self.mode)
