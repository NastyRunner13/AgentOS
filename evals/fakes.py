"""Scripted operator doubles for the eval suite."""

from __future__ import annotations

from pathlib import Path

import yaml

from kernel import Bus
from memory import Episodic
from tools.operator import Node, Operator


def perm(root: Path) -> dict:
    path = root / "config" / "permissions.yaml"
    if path.is_file():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "operator": {
            "max_verify_failures": 2,
            "min_ground_confidence": 0.5,
            "allowlist": {"notepad": {"exe": "notepad.exe"}, "browser": {"kind": "playwright"}},
            "ring": 1,
            "ring_other": 2,
        },
        "card": {"expiry_seconds": 300, "expire_action": "deny"},
        "shell": {"ring_other": 2, "allowlist": ["echo"]},
        "files": {"approved_roots": ["."], "read_ring": 0, "write_ring": 1},
    }


class ScriptedA11y:
    def __init__(self, elements: list[Node] | None = None, *, empty: bool = False) -> None:
        self.elements = [] if empty else list(elements or [Node("e1", "button", "OK")])
        self.clicks: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.document = ""
        self.keys_sent: list[str] = []

    async def open(self, app: str, url=None) -> None:
        self.opened.append(app)
        self.document = f"opened {app}"

    async def snapshot(self, app: str) -> list[Node]:
        return list(self.elements)

    async def click(self, ref: str) -> None:
        self.clicks.append(ref)

    async def type(self, ref: str, text: str) -> None:
        self.typed.append((ref, text))
        for n in self.elements:
            if n.ref == ref:
                n.value = text
        self.document += text

    async def keys(self, combo: str) -> None:
        self.keys_sent.append(combo)

    async def close(self, app: str) -> None:
        self.closed.append(app)

    async def read_state(self, app: str) -> str:
        names = " ".join(f"{n.name} {n.value}" for n in self.elements)
        return f"{self.document} {names}".strip()


class CapturingPixels:
    def __init__(self) -> None:
        self.shots = 0
        self.clicks: list[tuple[int, int]] = []
        self.typed: list[str] = []
        self.scrolls: list[tuple[int, int, int]] = []
        self.annotated = 0
        self.on_click = None
        self.size = (0, 0)

    async def screenshot(self) -> bytes:
        self.shots += 1
        return b"\x89PNG\r\n\x1a\n"

    async def annotate(self, png: bytes, leftover) -> bytes:
        self.annotated += 1
        return png

    async def click_xy(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))
        if self.on_click:
            self.on_click()

    async def scroll_xy(self, x: int, y: int, dy: int) -> None:
        self.scrolls.append((int(x), int(y), int(dy)))

    async def type_text(self, text: str) -> None:
        self.typed.append(text)


def operator(root: Path, a11y, pixels, ground=None, session_grants=None) -> Operator:
    bus = Bus()
    memory = Episodic(root / "events.db")
    return Operator(
        perm(root),
        bus,
        memory,
        root,
        a11y=a11y,
        pixels=pixels,
        ground=ground,
        session_grants=session_grants,
    )


# Compat names used by tests
_perm = perm
_operator = operator
