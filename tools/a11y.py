"""UIA / Playwright accessibility tree. Hands for the operator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


BROWSER_APPS = {"browser", "chrome", "msedge", "edge"}
INTERACTIVE_ARIA = {
    "button",
    "link",
    "textbox",
    "searchbox",
    "checkbox",
    "radio",
    "combobox",
    "menuitem",
    "tab",
    "slider",
    "spinbutton",
    "listbox",
    "option",
}


@dataclass
class Node:
    ref: str
    role: str
    name: str
    value: str = ""
    bounds: tuple[int, int, int, int] | None = None
    nth: int = 0


def untrusted(source: str, text: str) -> str:
    return f'<untrusted source="{source}">\n{text}\n</untrusted>'


def tree_text(nodes: list[Node]) -> str:
    if not nodes:
        return "(empty a11y tree)"
    lines = []
    for n in nodes:
        val = f" = {n.value!r}" if n.value else ""
        lines.append(f"[{n.ref}] {n.role} {n.name!r}{val}")
    return "\n".join(lines)


class LiveA11y:
    def __init__(self, tools: Any, perm: dict) -> None:
        self.tools = tools
        self.perm = perm
        self.kind = ""
        self.app = ""
        self._refs: dict[str, Any] = {}
        self._nodes: list[Node] = []
        self._win = None
        self._pyapp = None

    def _spec(self, app: str) -> dict:
        return dict((self.perm.get("operator") or {}).get("allowlist") or {}).get(app) or {}

    async def open(self, app: str, url: Any = None) -> None:
        self.app = app
        if app in BROWSER_APPS or (self._spec(app).get("kind") == "playwright"):
            self.kind = "browser"
            if self.tools is None:
                raise RuntimeError("browser tools missing")
            await self.tools.browser({"action": "navigate", "url": str(url or "about:blank")})
            return
        from pywinauto import Application

        self.kind = "uia"
        exe = str(self._spec(app).get("exe") or f"{app}.exe")
        self._pyapp = Application(backend="uia").start(exe)
        self._win = self._pyapp.top_window()

    async def snapshot(self, app: str) -> list[Node]:
        if self.kind == "browser" or app in BROWSER_APPS:
            return await self._snap_browser()
        return await self._snap_uia()

    async def click(self, ref: str) -> None:
        if self.kind == "browser":
            node = next((n for n in self._nodes if n.ref == ref), None)
            if node is None or self.tools is None or self.tools._page is None:
                raise KeyError(ref)
            page = self.tools._page
            loc = page.get_by_role(node.role, name=node.name) if node.name else page.get_by_role(node.role)
            await loc.nth(node.nth).click()
            return
        el = self._refs.get(ref)
        if el is None:
            raise KeyError(ref)
        try:
            el.click_input()
        except Exception:
            el.invoke()

    async def type(self, ref: str, text: str) -> None:
        if self.kind == "browser":
            node = next((n for n in self._nodes if n.ref == ref), None)
            if node is None or self.tools is None or self.tools._page is None:
                raise KeyError(ref)
            page = self.tools._page
            loc = page.get_by_role(node.role, name=node.name) if node.name else page.get_by_role(node.role)
            await loc.nth(node.nth).fill(text)
            return
        el = self._refs.get(ref)
        if el is None:
            raise KeyError(ref)
        try:
            el.set_edit_text(text)
        except Exception:
            el.type_keys(text, with_spaces=True)

    async def keys(self, combo: str) -> None:
        if self.kind == "browser" and self.tools and self.tools._page is not None:
            await self.tools._page.keyboard.press(combo)
            return
        if self._win is not None:
            self._win.type_keys(combo)

    async def close(self, app: str) -> None:
        if self.kind == "browser" and self.tools is not None:
            await self.tools.browser({"action": "close"})
            return
        if self._win is not None:
            self._win.close()

    async def read_state(self, app: str) -> str:
        nodes = await self.snapshot(app)
        extra = ""
        if self.kind == "browser" and self.tools and self.tools._page is not None:
            extra = await self.tools._page.locator("body").inner_text()
        elif self._win is not None:
            try:
                extra = self._win.window_text()
            except Exception:
                extra = ""
        return (tree_text(nodes) + "\n" + extra).strip()

    async def _snap_browser(self) -> list[Node]:
        if self.tools is None or self.tools._page is None:
            return []
        raw = await self.tools._page.accessibility.snapshot()
        nodes: list[Node] = []
        counts: dict[tuple[str, str], int] = {}
        self._walk_aria(raw or {}, nodes, counts)
        self._nodes = nodes
        return nodes

    def _walk_aria(self, raw: dict, nodes: list[Node], counts: dict[tuple[str, str], int]) -> None:
        role = str(raw.get("role") or "")
        name = str(raw.get("name") or "")
        key = (role, name)
        if role in INTERACTIVE_ARIA or (role and name):
            nth = counts.get(key, 0)
            counts[key] = nth + 1
            nodes.append(
                Node(
                    ref=f"e{len(nodes) + 1}",
                    role=role,
                    name=name,
                    value=str(raw.get("value") or ""),
                    nth=nth,
                )
            )
        for child in raw.get("children") or []:
            if isinstance(child, dict):
                self._walk_aria(child, nodes, counts)

    async def _snap_uia(self) -> list[Node]:
        if self._win is None:
            return []
        self._refs = {}
        nodes: list[Node] = []
        try:
            descendants = self._win.descendants()
        except Exception:
            return []
        for el in descendants[:80]:
            try:
                info = el.element_info
                name = str(info.name or "")
                role = str(info.control_type or "")
                if not name and role not in {"Button", "Edit", "MenuItem", "Hyperlink", "Document"}:
                    continue
                rect = info.rectangle
                bounds = (int(rect.left), int(rect.top), int(rect.right - rect.left), int(rect.bottom - rect.top))
            except Exception:
                continue
            ref = f"e{len(nodes) + 1}"
            nodes.append(Node(ref=ref, role=role.lower(), name=name, bounds=bounds))
            self._refs[ref] = el
        self._nodes = nodes
        return nodes
