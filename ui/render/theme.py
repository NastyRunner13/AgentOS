"""Shared Rich theme, console, and small format helpers."""

from __future__ import annotations

import shutil
import sys

from rich.console import Console
from rich.theme import Theme

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

FRIDAY_THEME = Theme(
    {
        "info": "dim #8b8b90",
        "warning": "bold #e0af68",
        "error": "bold #f38ba8",
        "success": "bold #00ff00",
        "thought": "italic #c0c0c0",
        "thought_dim": "dim #8b8b90",
        "tool": "bold #8db0ff",
        "diamond": "bold #e0af68",
        "diamond_dim": "#808080",
        "amber": "bold #e0af68",
        "silver": "#e1e1e1",
        "muted": "#8b8b90",
        "dim": "#6c6c6c",
        "ring0": "bold #00ff00",
        "ring1": "bold #e0af68",
        "ring2": "bold #f38ba8",
        "banner": "bold #e0af68",
        "you": "bold #8db0ff",
        "footer": "dim #8b8b90",
        "spinner": "bold #e0af68",
        "tool_ok": "bold #00ff00",
        "tool_run": "bold #e0af68",
        "tool_fail": "bold #f38ba8",
        "gutter": "#808080",
        "rule": "#404040",
    }
)

console = Console(theme=FRIDAY_THEME, highlight=False, soft_wrap=True, legacy_windows=False)

RING_STYLE = {0: "ring0", 1: "ring1", 2: "ring2", 3: "ring2"}
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def coerce_ring(ring, default: int = 1) -> int:
    if ring is None:
        return default
    return int(ring)


def clear_screen(out: Console | None = None) -> None:
    """Viewport + scrollback clear. `Console.clear()` alone leaves the old
    conversation visible above in Windows Terminal/conhost scrollback, which
    is why `/new` looked like it kept the previous chat."""
    c = out or console
    try:
        is_term = bool(c.is_terminal)
    except Exception:
        is_term = False
    if is_term:
        try:
            import os

            os.system("cls" if os.name == "nt" else "clear")
        except Exception:
            pass
    try:
        c.clear()
    except Exception:
        pass
    if is_term:
        # ESC[3J drops scrollback that cls/clear may leave behind.
        try:
            sys.stdout.write("\x1b[3J")
            sys.stdout.flush()
        except Exception:
            pass


def term_cols(out: Console | None = None) -> int:
    if out is not None:
        try:
            width = int(out.width or 0)
            if width >= 20:
                return width
        except Exception:
            pass
    try:
        return max(20, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except Exception:
        return 80


def fmt_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{max(1, int(seconds * 1000))}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    return f"{minutes}m{sec:02d}s"


def ring_label(ring: int) -> str:
    style = RING_STYLE.get(ring, "ring1")
    return f"[{style}]ring {ring}[/{style}]"
