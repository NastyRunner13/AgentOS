"""Native tools: shell, files, browser, computer (a11y-first operator)."""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Optional

from tools.browser import Browser
from tools.files import run as run_files
from tools.files import size as file_size
from tools.shell import powershell
from tools.shell import run as run_shell
from tools.specs import SPECS

__all__ = ["NativeTools", "SPECS"]


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
        self._shell_runner = shell_runner or powershell
        self._session = Browser(perm_cfg, clip=self._clip)
        self.operator = operator

    @property
    def _page(self):
        return self._session._page

    @property
    def _browser(self):
        return self._session._browser

    def file_size(self, path: str) -> int:
        return file_size(path, self.root, self.perm_cfg)

    async def execute(self, name: str, args: dict) -> str:
        if name == "shell":
            return await self.shell(args)
        if name == "files":
            return self.files(args)
        if name == "browser":
            return await self.browser(args)
        if name == "web_search":
            from tools import web as webmod

            return await webmod.search(str(args.get("query") or ""), self.perm_cfg, clip=self._clip)
        if name == "web_fetch":
            from tools import web as webmod

            return await webmod.fetch(str(args.get("url") or ""), self.perm_cfg, clip=self._clip)
        if name == "computer":
            if self.operator is None:
                return "operator not configured"
            return await self.operator.execute(args)
        return f"unknown tool {name}"

    async def shell(self, args: dict) -> str:
        return await run_shell(
            args,
            runner=self._shell_runner,
            perm_cfg=self.perm_cfg,
            root=self.root,
            clip=self._clip,
        )

    def files(self, args: dict) -> str:
        return run_files(args, root=self.root, perm_cfg=self.perm_cfg, clip=self._clip)

    async def browser(self, args: dict) -> str:
        return await self._session.run(args)

    def _clip(self, text: str) -> str:
        if len(text) <= self.max_chars:
            return text
        return text[: self.max_chars] + f"\n… truncated ({len(text)} chars)"
