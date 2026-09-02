"""Permission rings. Ring ≥2 raises a card and waits for resolve()."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from kernel.bus import Bus, new_id


class Gate:
    def __init__(self, cfg: dict, bus: Bus, session_grants: set[str] | None = None) -> None:
        self.cfg = cfg
        self.bus = bus
        self._pending: dict[str, asyncio.Future] = {}
        self._cards: dict[str, dict] = {}
        self.session_grants = session_grants if session_grants is not None else set()

    def classify(self, tool: str, args: dict) -> int:
        if tool == "shell":
            return self._shell_ring(str(args.get("command", "")))
        if tool == "files":
            return self._files_ring(args)
        if tool == "browser":
            return int(self.cfg.get("browser", {}).get("ring", 1))
        if tool == "computer":
            return self._computer_ring(args)
        if tool == "web_search":
            return int(self.cfg.get("web", {}).get("search_ring", 0))
        if tool == "web_fetch":
            return int(self.cfg.get("web", {}).get("fetch_ring", 0))
        if tool == "skill":
            return 0
        if tool == "spawn_task":
            return 0
        if tool == "kb_read":
            return 0
        if tool in ("kb_propose", "kb_consolidate"):
            return 1
        if tool == "ask_user":
            return 0
        return 2

    def _shell_ring(self, command: str) -> int:
        shell = self.cfg.get("shell", {})
        allowlisted = int(shell.get("ring_allowlisted", 1))
        other = int(shell.get("ring_other", 2))
        cmd = command.strip()
        chaining = (";", "&", "|", "\n", "\r", "$(", "`")
        if any(c in cmd for c in chaining):
            return other
        for pattern in shell.get("allowlist") or []:
            p = str(pattern).strip()
            if cmd == p or cmd.startswith(p + " ") or cmd.startswith(p + "\t"):
                return allowlisted
        return other

    def _computer_ring(self, args: dict) -> int:
        op = self.cfg.get("operator") or {}
        silent = int(op.get("ring", 1))
        other = int(op.get("ring_other", 2))
        action = str(args.get("action") or "")
        if action in {"see", "snapshot", "list_windows"}:
            return silent
        app = str(args.get("app") or "").strip().lower()
        xy = args.get("x") is not None and args.get("y") is not None
        if xy and action in {"click", "type", "keys", "scroll"} and not app:
            return silent
        if not app:
            return silent
        if app in self.session_grants:
            return silent
        allow = {str(k).lower() for k in (op.get("allowlist") or {})}
        if app in allow:
            return silent
        return other

    def _grant_computer(self, tool: str, args: dict) -> None:
        if tool != "computer":
            return
        app = str(args.get("app") or "").strip().lower()
        if app:
            self.session_grants.add(app)

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
        target = str(args.get("path") or "").replace("\\", "/").strip().lower()
        dest = str(args.get("dest") or "").replace("\\", "/").strip().lower()
        for p in (target, dest):
            if not p:
                continue
            name = p.split("/")[-1]
            if (
                name in (".env", "permissions.yaml", "models.yaml", "kernel.yaml", "memory.yaml")
                or name.endswith(".py")
                or p.startswith("config/")
                or "/config/" in p
                or p.startswith("kernel/")
                or "/kernel/" in p
                or p.startswith(".git/")
                or "/.git/" in p
            ):
                return 2
        return int(files.get("write_ring", 1))

    def preview(self, tool: str, args: dict) -> str:
        if tool == "shell":
            return f"shell: {args.get('command', '')}"
        if tool == "files":
            return f"files {args.get('action', '')}: {args.get('path', args)}"
        if tool == "browser":
            return f"browser {args.get('action', '')}: {args.get('url') or args.get('ref') or ''}"
        if tool == "computer":
            extra = " (not on operator allowlist)" if self._computer_ring(args) >= 2 else ""
            xy = ""
            if args.get("x") is not None and args.get("y") is not None:
                xy = f" @{args.get('x')},{args.get('y')}"
            return (
                f"computer {args.get('action', '')} {args.get('app', '')} "
                f"{args.get('ref') or ''}{xy}{extra}"
            ).strip()
        if tool == "kb_propose":
            return f"kb_propose: {args.get('statement') or args.get('name') or args}"
        if tool == "kb_consolidate":
            return "kb_consolidate"
        if tool == "kb_read":
            return f"kb_read: {args.get('query', '')}"
        if tool == "web_search":
            site = str(args.get("site") or "").strip()
            extra = f" site:{site}" if site else ""
            return f"web_search: {args.get('query', '')}{extra}"
        if tool == "web_fetch":
            return f"web_fetch: {args.get('url', '')}"
        if tool == "skill":
            return f"skill: {args.get('name', '')}"
        if tool == "ask_user":
            return f"ask_user: {args.get('question', '')}"
        return f"{tool}: {args}"

    async def check(self, tool: str, args: dict, reason: str = "") -> bool:
        ring = self.classify(tool, args)
        if ring <= 1:
            return True
        card_id = new_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[card_id] = fut
        self._cards[card_id] = {"fut": fut, "kind": "permission"}
        expiry = int(self.cfg.get("card", {}).get("expiry_seconds", 300))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
        self.bus.publish(
            "approval.request",
            {
                "id": card_id,
                "kind": "permission",
                "action_preview": self.preview(tool, args),
                "reason": reason or f"ring {ring}",
                "ring": ring,
                "expires_at": expires_at.isoformat(),
                "tool": tool,
            },
        )
        try:
            approved = bool(await asyncio.wait_for(asyncio.shield(fut), timeout=expiry))
        except asyncio.TimeoutError:
            if not fut.done():
                expire_ok = str(self.cfg.get("card", {}).get("expire_action", "deny")) == "allow"
                fut.set_result(expire_ok)
            self._pending.pop(card_id, None)
            self._cards.pop(card_id, None)
            approved = bool(fut.result())
            self.bus.publish(
                "approval.resolved",
                {"id": card_id, "approved": approved, "expired": True},
            )
            if approved:
                self._grant_computer(tool, args)
            return approved
        if approved:
            self._grant_computer(tool, args)
        return approved

    async def ask(
        self,
        question: str,
        options: list[str],
        *,
        allow_custom: bool = True,
        timeout: float = 300.0,
    ) -> str:
        card_id = new_id()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[card_id] = fut
        self._cards[card_id] = {
            "fut": fut,
            "kind": "question",
            "question": question,
            "options": options,
            "allow_custom": allow_custom,
        }
        expiry = int(timeout or self.cfg.get("card", {}).get("expiry_seconds", 300))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiry)
        self.bus.publish(
            "approval.request",
            {
                "id": card_id,
                "kind": "question",
                "question": question,
                "options": options,
                "allow_custom": allow_custom,
                "ring": 0,
                "action_preview": f"Question: {question}",
                "reason": "Clarification needed",
                "expires_at": expires_at.isoformat(),
                "tool": "ask_user",
            },
        )
        try:
            return str(await asyncio.wait_for(asyncio.shield(fut), timeout=expiry))
        except asyncio.TimeoutError:
            default_ans = options[0] if options else "cancelled"
            if not fut.done():
                fut.set_result(default_ans)
            self._pending.pop(card_id, None)
            self._cards.pop(card_id, None)
            self.bus.publish(
                "approval.resolved",
                {"id": card_id, "approved": True, "answer": default_ans, "expired": True},
            )
            return default_ans

    def resolve(self, card_id: str, approved: object) -> bool:
        fut = self._pending.pop(card_id, None)
        card_info = self._cards.pop(card_id, None) or {}
        if fut is None or fut.done():
            return False
        kind = card_info.get("kind", "permission")
        if kind == "question":
            if isinstance(approved, bool):
                opts = card_info.get("options") or []
                answer = opts[0] if (approved and opts) else "cancelled"
            else:
                answer = str(approved)
            fut.set_result(answer)
            self.bus.publish(
                "approval.resolved",
                {"id": card_id, "approved": answer != "cancelled", "answer": answer, "expired": False},
            )
            return True
        fut.set_result(bool(approved))
        self.bus.publish(
            "approval.resolved",
            {"id": card_id, "approved": bool(approved), "expired": False},
        )
        return True

    def get_card(self, card_id: str) -> dict | None:
        return self._cards.get(card_id)

    def pending(self) -> list[str]:
        return list(self._pending)
