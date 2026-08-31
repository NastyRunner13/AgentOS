"""Permission rings. Ring ≥2 raises a card and waits for resolve()."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from kernel.bus import Bus, new_id


class Gate:
    def __init__(self, cfg: dict, bus: Bus) -> None:
        self.cfg = cfg
        self.bus = bus
        self._pending: dict[str, asyncio.Future] = {}

    def classify(self, tool: str, args: dict) -> int:
        if tool == "shell":
            return self._shell_ring(str(args.get("command", "")))
        if tool == "files":
            return self._files_ring(args)
        if tool == "browser":
            return int(self.cfg.get("browser", {}).get("ring", 1))
        if tool == "computer":
            return int(self.cfg.get("operator", {}).get("ring", 1))
        if tool == "web_search":
            return int(self.cfg.get("web", {}).get("search_ring", 0))
        if tool == "web_fetch":
            return int(self.cfg.get("web", {}).get("fetch_ring", 0))
        if tool == "spawn_task":
            return 0
        if tool == "kb_read":
            return 0
        if tool in ("kb_propose", "kb_consolidate"):
            return 1
        return 2

    def _shell_ring(self, command: str) -> int:
        shell = self.cfg.get("shell", {})
        allowlisted = int(shell.get("ring_allowlisted", 1))
        other = int(shell.get("ring_other", 2))
        cmd = command.strip()
        for pattern in shell.get("allowlist") or []:
            p = str(pattern).strip()
            if cmd == p or cmd.startswith(p + " ") or cmd.startswith(p + "\t"):
                return allowlisted
        return other

    def _files_ring(self, args: dict) -> int:
        files = self.cfg.get("files", {})
        action = str(args.get("action", "read"))
        if action == "read" or action == "search":
            return int(files.get("read_ring", 0))
        if action == "delete":
            threshold = int(files.get("delete_size_threshold_bytes", 1048576))
            size = int(args.get("_size", 0))
            if size >= threshold:
                return int(files.get("delete_over_threshold_ring", 3))
            return int(files.get("delete_ring", 2))
        return int(files.get("write_ring", 1))

    def preview(self, tool: str, args: dict) -> str:
        if tool == "shell":
            return f"shell: {args.get('command', '')}"
        if tool == "files":
            return f"files {args.get('action', '')}: {args.get('path', args)}"
        if tool == "browser":
            return f"browser {args.get('action', '')}: {args.get('url') or args.get('ref') or ''}"
        if tool == "computer":
            return f"computer {args.get('action', '')} {args.get('app', '')} {args.get('ref') or ''}".strip()
        if tool == "kb_propose":
            return f"kb_propose: {args.get('statement') or args.get('name') or args}"
        if tool == "kb_consolidate":
            return "kb_consolidate"
        if tool == "kb_read":
            return f"kb_read: {args.get('query', '')}"
        if tool == "web_search":
            return f"web_search: {args.get('query', '')}"
        if tool == "web_fetch":
            return f"web_fetch: {args.get('url', '')}"
        return f"{tool}: {args}"

    async def check(self, tool: str, args: dict, reason: str = "") -> bool:
        ring = self.classify(tool, args)
        if ring <= 1:
            return True
        card_id = new_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[card_id] = fut
        expiry = int(self.cfg.get("card", {}).get("expiry_seconds", 300))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
        self.bus.publish(
            "approval.request",
            {
                "id": card_id,
                "action_preview": self.preview(tool, args),
                "reason": reason or f"ring {ring}",
                "ring": ring,
                "expires_at": expires_at.isoformat(),
                "tool": tool,
            },
        )
        try:
            return bool(await asyncio.wait_for(asyncio.shield(fut), timeout=expiry))
        except asyncio.TimeoutError:
            if not fut.done():
                expire_ok = str(self.cfg.get("card", {}).get("expire_action", "deny")) == "allow"
                fut.set_result(expire_ok)
            self._pending.pop(card_id, None)
            self.bus.publish(
                "approval.resolved",
                {"id": card_id, "approved": bool(fut.result()), "expired": True},
            )
            return bool(fut.result())

    def resolve(self, card_id: str, approved: bool) -> bool:
        fut = self._pending.pop(card_id, None)
        if fut is None or fut.done():
            return False
        fut.set_result(bool(approved))
        self.bus.publish(
            "approval.resolved",
            {"id": card_id, "approved": bool(approved), "expired": False},
        )
        return True

    def pending(self) -> list[str]:
        return list(self._pending)
