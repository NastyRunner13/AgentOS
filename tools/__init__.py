"""Native tools: shell, files, browser, computer (a11y-first operator)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable, Optional


SPECS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Run a PowerShell command. Output is truncated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "files",
            "description": "Read, write, move, search, or delete files inside approved roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["read", "write", "move", "search", "delete"],
                    },
                    "path": {"type": "string"},
                    "dest": {"type": "string"},
                    "content": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["action", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser",
            "description": "Control a Chromium page: navigate, snapshot, click, type, close.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["navigate", "snapshot", "click", "type", "close"],
                    },
                    "url": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_task",
            "description": "Start a background task. Returns the task id for later steer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["title", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "computer",
            "description": (
                "Desktop operator for allowlisted apps and the browser. "
                "A11y first, pixels last. Every action is verified by re-reading state."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "snapshot", "click", "type", "keys", "close"],
                    },
                    "app": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "url": {"type": "string"},
                    "expect": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_read",
            "description": "Recall user-confirmed facts. Pending proposals are not returned.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_propose",
            "description": (
                "Draft a memory proposal (fact, entity, or edge). "
                "It stays pending until the user approves it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["fact", "entity", "edge", "preference"]},
                    "statement": {"type": "string"},
                    "entity_kind": {"type": "string", "enum": ["Person", "Project", "Preference"]},
                    "name": {"type": "string"},
                    "attrs": {"type": "object"},
                    "src": {"type": "string"},
                    "rel": {"type": "string", "enum": ["OWNS", "ABOUT", "SUPERSEDES"]},
                    "dst": {"type": "string"},
                    "about": {"type": "string"},
                    "supersedes": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_consolidate",
            "description": (
                "Run the librarian on recent episodes. Drafts proposals only; "
                "never writes confirmed facts."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class NativeTools:
    def __init__(
        self,
        root: Path,
        perm_cfg: dict,
        *,
        max_chars: int = 8000,
        shell_runner: Optional[Callable[[str, float, Path], Awaitable[str]]] = None,
        operator=None,
    ) -> None:
        self.root = root.resolve()
        self.perm_cfg = perm_cfg
        self.max_chars = max_chars
        self._shell_runner = shell_runner or self._powershell
        self._browser = None
        self._page = None
        self.operator = operator

    def file_size(self, path: str) -> int:
        try:
            p = self._resolve(path)
        except ValueError:
            return 0
        return p.stat().st_size if p.exists() and p.is_file() else 0

    async def execute(self, name: str, args: dict) -> str:
        if name == "shell":
            return await self.shell(args)
        if name == "files":
            return self.files(args)
        if name == "browser":
            return await self.browser(args)
        if name == "computer":
            if self.operator is None:
                return "operator not configured"
            return await self.operator.execute(args)
        return f"unknown tool {name}"

    async def shell(self, args: dict) -> str:
        command = str(args.get("command", "")).strip()
        if not command:
            return "empty command"
        timeout = float(args.get("timeout_seconds") or self.perm_cfg.get("shell", {}).get("timeout_seconds", 60))
        cwd_raw = self.perm_cfg.get("shell", {}).get("working_directory", ".")
        cwd = Path(cwd_raw)
        if not cwd.is_absolute():
            cwd = (self.root / cwd).resolve()
        return self._clip(await self._shell_runner(command, timeout, cwd))

    async def _powershell(self, command: str, timeout: float, cwd: Path) -> str:
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return f"timed out after {timeout}s"
        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        code = proc.returncode
        body = out if not err else (out + ("\n" if out else "") + err)
        return body if code == 0 else f"exit {code}\n{body}"

    def files(self, args: dict) -> str:
        action = str(args.get("action", "read"))
        path = str(args.get("path", ""))
        try:
            p = self._resolve(path)
        except ValueError as exc:
            return str(exc)
        if action == "read":
            if not p.is_file():
                return f"not a file: {p}"
            return self._clip(p.read_text(encoding="utf-8", errors="replace"))
        if action == "write":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(args.get("content", "")), encoding="utf-8")
            return f"wrote {p}"
        if action == "move":
            dest = self._resolve(str(args.get("dest", "")))
            dest.parent.mkdir(parents=True, exist_ok=True)
            p.replace(dest)
            return f"moved {p} -> {dest}"
        if action == "delete":
            if p.is_dir():
                return "refusing to delete a directory"
            try:
                p.unlink()
            except FileNotFoundError:
                return f"missing {p}"
            return f"deleted {p}"
        if action == "search":
            query = str(args.get("query", ""))
            hits = []
            if p.is_file():
                scan = [p]
            else:
                scan = [x for x in p.rglob("*") if x.is_file()]
            for f in scan[:200]:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if query in text or query in f.name:
                    hits.append(str(f))
                if len(hits) >= 50:
                    break
            return json.dumps(hits)
        return f"unknown files action {action}"

    async def browser(self, args: dict) -> str:
        action = str(args.get("action", "snapshot"))
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "playwright not installed"
        headless = bool(self.perm_cfg.get("browser", {}).get("headless", False))
        if action == "close":
            if self._browser:
                await self._browser.close()
                self._browser = None
                self._page = None
            return "closed"
        if self._browser is None:
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=headless)
            self._page = await self._browser.new_page()
        page = self._page
        if action == "navigate":
            url = str(args.get("url", ""))
            await page.goto(url)
            return f"navigated {page.url}"
        if action == "snapshot":
            text = await page.locator("body").inner_text()
            return f'<untrusted source="web">\n{text}\n</untrusted>'
        if action == "click":
            await page.locator(str(args.get("ref", "body"))).first.click()
            return "clicked"
        if action == "type":
            await page.locator(str(args.get("ref", "body"))).first.fill(str(args.get("text", "")))
            return "typed"
        return f"unknown browser action {action}"

    def _resolve(self, raw: str) -> Path:
        if not raw:
            raise ValueError("missing path")
        p = Path(raw)
        if not p.is_absolute():
            p = (self.root / p)
        p = p.resolve()
        roots = []
        for r in self.perm_cfg.get("files", {}).get("approved_roots") or ["."]:
            rp = Path(r).expanduser()
            if not rp.is_absolute():
                rp = (self.root / rp)
            roots.append(rp.resolve())
        if not any(_within(p, r) for r in roots):
            raise ValueError(f"path {p} is outside approved roots")
        return p

    def _clip(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars] + f"\n… truncated ({len(text)} chars)"
