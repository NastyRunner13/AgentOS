"""Permission and question cards."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ui.render.theme import console, term_cols


def render_question_card(ev: dict[str, Any], out: Console | None = None) -> None:
    """Left-border multiple-choice question card for pre-implementation unclarities."""
    c = out or console
    width = term_cols(c)
    cid = ev.get("id", "unknown")
    question = ev.get("question") or ev.get("action_preview") or "Clarification needed"
    options = ev.get("options") or []
    allow_custom = ev.get("allow_custom", True)
    inner = max(16, width - 12)

    body = Text()
    accent = "bold #89b4fa"
    body.append("┃  ◆ Clarification needed\n", style=accent)
    body.append("┃  ", style="dim #8b8b90")
    body.append(f"{str(question)[:inner]}\n\n", style="bold white")
    for idx, opt in enumerate(options, 1):
        body.append(f"┃  ({idx}) ", style="bold #a6e3a1")
        body.append(f"{str(opt)[:inner]}\n", style="white")
    if allow_custom:
        body.append("┃  (c) ", style="bold #fab387")
        body.append("Custom write-in\n", style="dim #c0c0c0")

    c.print(
        Panel(
            body,
            title=f"card {cid} · choice",
            border_style="#89b4fa",
            padding=(0, 1),
            expand=False,
            width=min(width, 100),
        )
    )


def render_card(ev: dict[str, Any], out: Console | None = None) -> None:
    """Left-border permission or question card. Inline y/n is the live path; /approve remains."""
    if ev.get("kind") == "question":
        render_question_card(ev, out=out)
        return
    c = out or console
    width = term_cols(c)
    cid = ev.get("id", "unknown")
    ring = ev.get("ring", 2)
    action = ev.get("action_preview", "")
    reason = ev.get("reason", "Host mutation requires permission")
    inner = max(16, width - 12)

    body = Text()
    accent = "bold #f38ba8" if int(ring) >= 2 else "bold #e0af68"
    body.append("┃  ◆ Permission request", style=accent)
    body.append(f"  ring {ring}\n", style=accent)
    body.append("┃  Action:  ", style="dim #8b8b90")
    body.append(f"{str(action)[:inner]}\n", style="bold white")
    body.append("┃  Reason:  ", style="dim #8b8b90")
    body.append(f"{str(reason)[:inner]}\n\n", style="italic #c0c0c0")
    body.append("┃  (●) 1. Allow               ", style="bold #00ff00")
    body.append(f"[y / /approve {cid}]\n", style="dim #6c6c6c")
    body.append("┃  (○) 2. Deny                ", style="bold #f38ba8")
    body.append(f"[n / /deny {cid}]", style="dim #6c6c6c")

    c.print(
        Panel(
            body,
            title=f"card {cid} · ring {ring}",
            border_style="#f38ba8" if int(ring) >= 2 else "#e0af68",
            padding=(0, 1),
            expand=False,
            width=min(width, 100),
        )
    )
