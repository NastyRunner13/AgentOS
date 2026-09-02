"""Rich console rendering for the Friday CLI transcript."""

from __future__ import annotations

import shutil
import sys
import time
from typing import Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

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


def coerce_ring(ring, default: int = 1) -> int:
    if ring is None:
        return default
    return int(ring)
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

FRIDAY_BRAILLE_LOGO = [
    "  ⢀⣤⣶⣶⣶⣶⣶⣤⡀  ",
    "  ⢸⣿⣿⠛⠉⠉⠉⠉⠁  ",
    "  ⢸⣿⣿⣶⣶⣶⣶⣤⡀  ",
    "  ⢸⣿⣿⠉⠉⠉⠉⠉⠁  ",
    "  ⠘⢿⣿⣿         ",
]


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


def _ring_label(ring: int) -> str:
    style = RING_STYLE.get(ring, "ring1")
    return f"[{style}]ring {ring}[/{style}]"


def _short_args(args: dict[str, Any], width: int = 56) -> str:
    if not args:
        return ""
    if "command" in args:
        text = str(args.get("command") or "")
    elif "path" in args:
        action = args.get("action") or "read"
        text = f"{action} {args.get('path')}"
    elif "url" in args:
        text = str(args.get("url") or "")
    elif "query" in args:
        text = str(args.get("query") or "")
    else:
        skip = {"content", "_size"}
        text = " ".join(f"{k}={v}" for k, v in list(args.items())[:3] if k not in skip)
    text = " ".join(text.split())
    width = max(12, width)
    return text if len(text) <= width else text[: width - 1] + "…"


def _tool_heading(
    name: str,
    args: dict[str, Any],
    ring: int,
    suffix: str = "",
    *,
    width: int = 80,
) -> Text:
    """Left-gutter tool line: ┃  ◆ files  write path  ring N  ✓ done 40ms."""
    if suffix.startswith("done"):
        status_icon, status_style = "✓", "tool_ok"
    elif suffix.startswith("running"):
        status_icon, status_style = "⏳", "tool_run"
    elif suffix.startswith("denied") or suffix.startswith("fail"):
        status_icon, status_style = "✗", "tool_fail"
    else:
        status_icon, status_style = "›", "dim"

    arg_width = max(12, width - 36 - len(name) - len(suffix))
    line = Text()
    line.append("┃  ", style="gutter")
    line.append("◆ ", style="diamond")
    line.append(name, style="bold")
    summary = _short_args(args, arg_width)
    if summary:
        line.append("  ")
        line.append(summary, style="dim")
    line.append("  ")
    line.append_text(Text.from_markup(_ring_label(ring)))
    if suffix:
        line.append("  ")
        line.append(f"{status_icon} {suffix}", style=status_style)
    return line


def _gutter_preview(text: str, width: int = 72) -> Text:
    preview = " ".join(text.split())
    width = max(12, width)
    if len(preview) > width:
        preview = preview[: width - 1] + "…"
    line = Text("┃  │ ", style="gutter")
    line.append(preview, style="dim")
    return line


def _write_preview(args: dict[str, Any], result: str, width: int) -> list[Text]:
    """Compact file-write snippet; other tools get a single gutter preview."""
    lines: list[Text] = []
    inner = max(16, width - 10)
    action = str(args.get("action") or "")
    content = str(args.get("content") or "")
    if result:
        lines.append(_gutter_preview(result, inner + 4))
    if content and action == "write":
        raw = content.splitlines() or [content]
        shown = raw[:8]
        for i, row in enumerate(shown, 1):
            t = Text("┃  │ ", style="gutter")
            t.append(f"{i:3d} ", style="dim")
            t.append(row[:inner], style="silver")
            lines.append(t)
        extra = len(raw) - len(shown)
        if extra > 0:
            t = Text("┃  │ ", style="gutter")
            t.append(f"… +{extra} lines", style="dim")
            lines.append(t)
    return lines


def render_banner(
    model: str = "claude-3-7-sonnet",
    mode: str = "Code",
    *,
    cwd: str = "",
    branch: str = "",
    session_id: str = "",
    title: str = "",
    out: Console | None = None,
) -> None:
    """Launch card: logo + workspace facts. Compacts as the terminal narrows."""
    c = out or console
    width = term_cols(c)

    if width < 52:
        line = Text()
        line.append("Friday", style="bold white")
        if cwd:
            line.append("  ")
            line.append(cwd, style="white")
        if branch:
            line.append("  ")
            line.append(branch, style="bold #00ff00")
        if session_id:
            line.append("  ")
            line.append(session_id, style="dim #8b8b90")
        line.append("  ")
        line.append(mode, style="bold #e0af68")
        if model:
            short = model.split("/")[-1] if "/" in model else model
            line.append("  ")
            line.append(short, style="dim #8b8b90")
        c.print(line)
        c.print()
        return

    info_grid = Table.grid(expand=True)
    info_grid.add_column(justify="left", ratio=1, overflow="ellipsis")

    top_line = Text()
    top_line.append("Friday AgentOS", style="bold white")
    top_line.append("  v0.1.0", style="dim #8b8b90")
    if session_id:
        top_line.append("  ·  ", style="dim #6c6c6c")
        top_line.append(f"session {session_id}", style="dim #8b8b90")
    if title and width >= 72:
        top_line.append(f" ({title})", style="dim #6c6c6c")
    info_grid.add_row(top_line)

    headline = Text()
    headline.append("Agent kernel ready", style="bold #e0af68")
    headline.append(f" in {mode} mode", style="bold white")
    info_grid.add_row(headline)

    meta_line = Text()
    if cwd:
        meta_line.append(cwd, style="white")
    if branch:
        if cwd:
            meta_line.append("  ·  ", style="dim #6c6c6c")
        meta_line.append(f"git:{branch}", style="bold #00ff00")
    if model:
        if cwd or branch:
            meta_line.append("  ·  ", style="dim #6c6c6c")
        meta_line.append(model, style="dim #8b8b90")
    info_grid.add_row(meta_line)

    menu_table = Table.grid(padding=(0, 2))
    menu_table.add_column(style="white", overflow="ellipsis")
    menu_table.add_column(style="dim #6c6c6c", overflow="ellipsis")
    menu_table.add_row("◆ New session", "/new")
    menu_table.add_row("◆ Resume session", "/resume")
    if width >= 64:
        menu_table.add_row("◆ Keyboard shortcuts", "Ctrl+X / /shortcuts")
        menu_table.add_row("◆ Agent dials & skills", "/mode · /skills · /settings")
    menu_table.add_row("◆ Exit Friday", "/exit")
    info_grid.add_row(Text())
    info_grid.add_row(menu_table)

    if width < 78:
        body: RenderableType = info_grid
    else:
        logo_text = Text()
        for row in FRIDAY_BRAILLE_LOGO:
            logo_text.append(row + "\n", style="bold #e0af68")
        card_grid = Table.grid(expand=True, padding=(0, 2))
        card_grid.add_column(width=18, justify="center", no_wrap=True)
        card_grid.add_column(justify="left", ratio=1, overflow="ellipsis")
        card_grid.add_row(logo_text, info_grid)
        body = card_grid

    c.print(
        Panel(
            body,
            border_style="#505050",
            padding=(1, 1 if width < 78 else 2),
            expand=False,
            width=min(width, 100),
        )
    )
    if width >= 64:
        c.print(
            "[dim #8b8b90]Shift+Tab cycles Code / Architect / Ask / Fast · "
            "Ctrl+X shortcuts[/dim #8b8b90]\n"
        )
    else:
        c.print()


def display_user_content(content: str) -> str:
    """Collapse stored skill turns and @file attachments for the transcript."""
    from ui.mentions import strip_attachments

    content = strip_attachments(content)
    if not content.startswith("[skill:"):
        return content
    first, _, _rest = content.partition("\n")
    name = first[len("[skill:") :].rstrip("]")
    marker = "User request:"
    idx = content.rfind(marker)
    request = content[idx + len(marker) :].strip() if idx != -1 else ""
    if not request or request == "Follow the skill instructions.":
        return f"/{name}"
    return f"/{name} {request}"


def render_history(history: list[dict[str, Any]], out: Console | None = None) -> None:
    c = out or console
    for msg in history:
        role = msg.get("role")
        content = str(msg.get("content") or "")
        if role == "user":
            render_user(display_user_content(content), out=c)
        elif role == "assistant" and content.strip():
            c.print("[bold #e0af68]Friday[/bold #e0af68]")
            c.print(Markdown(content))
            c.print()


def render_user(text: str, out: Console | None = None) -> None:
    c = out or console
    c.print()
    line = Text()
    line.append("❯ ", style="bold #8db0ff")
    line.append(text, style="white")
    c.print(line)


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
            expand=width >= 60,
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
            expand=width >= 60,
        )
    )


def render_plan(
    filename: str = "plan.md",
    lines: list[str] | None = None,
    status: str = "",
    out: Console | None = None,
) -> None:
    """Print a plan viewer. Does not invent a plan."""
    c = out or console
    if not lines:
        c.print(f"[dim #8b8b90]No {filename} in the workspace.[/dim #8b8b90]")
        return

    width = term_cols(c)
    inner = max(16, width - 10)
    content = Text()
    for idx, raw in enumerate(lines[:80], 1):
        content.append(f"{idx:3d} │ ", style="dim #6c6c6c")
        content.append(f"{raw[:inner]}\n", style="white")
    if len(lines) > 80:
        content.append(f"    │ … +{len(lines) - 80} lines\n", style="dim #6c6c6c")

    header = Text()
    header.append("◆ ", style="bold #e0af68")
    header.append(filename, style="bold #e0af68")
    if status:
        header.append(f"  {status.replace('_', ' ')}", style="dim #8b8b90")

    bits: list[RenderableType] = [header, Text(), content]
    if status == "waiting_approval":
        actions = Text()
        actions.append("a", style="bold #00ff00")
        actions.append(" approve", style="dim #8b8b90")
        actions.append(" | ", style="dim #6c6c6c")
        actions.append("s", style="bold #e0af68")
        actions.append(" request changes", style="dim #8b8b90")
        actions.append(" | ", style="dim #6c6c6c")
        actions.append("c", style="bold #8db0ff")
        actions.append(" comment", style="dim #8b8b90")
        actions.append(" | ", style="dim #6c6c6c")
        actions.append("q", style="bold #f38ba8")
        actions.append(" quit plan", style="dim #8b8b90")
        bits.append(Text())
        bits.append(actions)
        wait = Text()
        wait.append("◆ ", style="bold #e0af68")
        wait.append("Waiting on plan approval", style="thought")
        bits.append(wait)
    elif status == "approved":
        bits.append(Text())
        bits.append(Text("◆ Plan approved", style="success"))
    elif status == "discarded":
        bits.append(Text())
        bits.append(Text("◆ Plan discarded", style="warning"))
    elif status == "changes_requested":
        bits.append(Text())
        bits.append(Text("◆ Changes requested", style="amber"))

    c.print(
        Panel(
            Group(*bits),
            title=filename,
            border_style="#e0af68",
            padding=(0, 1),
        )
    )


def render_plans(
    rows: list[dict[str, Any]],
    current_id: str = "",
    out: Console | None = None,
) -> None:
    c = out or console
    if not rows:
        c.print("[dim #8b8b90]No saved plans.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Saved Plans",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("ID", style="dim #8b8b90", min_width=8, max_width=12)
    table.add_column("Status", style="bold #e0af68", min_width=10, max_width=18)
    table.add_column("Updated", style="white", min_width=12, max_width=20)
    table.add_column("Title", style="white", overflow="fold")
    for row in rows:
        pid = str(row.get("id", ""))
        marker = "● " if pid == current_id else "  "
        table.add_row(
            marker + pid,
            str(row.get("status") or "").replace("_", " "),
            str(row.get("updated_at", ""))[:19].replace("T", " "),
            str(row.get("title") or "(untitled)"),
        )
    c.print(table)
    c.print(
        "[dim #8b8b90]/plan to open the current one · /plan <id> to load[/dim #8b8b90]"
    )


def render_shortcuts() -> None:
    from ui.dialogs import show_shortcuts_dialog

    show_shortcuts_dialog()


def render_tool_call(tool_name: str, args: dict[str, Any], ring: int = 1) -> None:
    console.print(_tool_heading(tool_name, args, ring, "running", width=term_cols()))


def render_facts(facts: list[dict[str, Any]], out: Console | None = None) -> None:
    c = out or console
    if not facts:
        c.print("[dim #8b8b90]No confirmed long-term facts in memory.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Confirmed Facts",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("ID", style="dim #8b8b90", min_width=6, max_width=10)
    table.add_column("Fact", style="white", ratio=4, overflow="fold")
    table.add_column("Confidence", style="bold #00ff00", min_width=8, justify="center")
    for f in facts:
        conf = f.get("confidence", 1.0)
        table.add_row(
            str(f.get("id", "")),
            str(f.get("statement", "")),
            f"{conf:.0%}" if isinstance(conf, (int, float)) else str(conf),
        )
    c.print(table)


def render_proposals(proposals: list[dict[str, Any]], out: Console | None = None) -> None:
    c = out or console
    if not proposals:
        c.print("[dim #8b8b90]No pending Librarian proposals.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Pending Librarian Proposals",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("ID", style="dim #8b8b90", min_width=6, max_width=10)
    table.add_column("Kind", style="bold #8db0ff", min_width=8, max_width=12)
    table.add_column("Preview", style="white", ratio=4, overflow="fold")
    for p in proposals:
        payload = p.get("payload", {})
        preview = payload.get("statement") or payload.get("name") or str(payload)
        table.add_row(str(p.get("id", "")), str(p.get("kind", "")), str(preview))
    c.print(table)
    c.print(
        "[dim #8b8b90]Approve with [bold white]/approve <id>[/bold white] "
        "or [bold white]/approve all[/bold white][/dim #8b8b90]"
    )


def render_tasks(tasks: list[Any], out: Console | None = None) -> None:
    c = out or console
    if not tasks:
        c.print("[dim #8b8b90]No tasks in queue.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Agent Tasks",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("ID", style="dim #8b8b90", min_width=6, max_width=10)
    table.add_column("Status", style="bold", min_width=10, max_width=16)
    table.add_column("Title", style="white", ratio=3, overflow="fold")
    status_styles = {
        "running": "[bold #00ff00]running[/bold #00ff00]",
        "queued": "[bold #e0af68]queued[/bold #e0af68]",
        "done": "[dim #8b8b90]done[/dim #8b8b90]",
        "failed": "[bold #f38ba8]failed[/bold #f38ba8]",
        "stuck": "[bold #e0af68]stuck[/bold #e0af68]",
        "waiting_approval": "[bold #f38ba8]card[/bold #f38ba8]",
    }
    for t in tasks:
        st = getattr(t, "status", "unknown")
        table.add_row(str(getattr(t, "id", "")), status_styles.get(st, st), str(getattr(t, "title", "")))
    c.print(table)


def render_roles(roles_cfg: dict[str, Any], out: Console | None = None) -> None:
    c = out or console
    if not roles_cfg:
        c.print("[dim #8b8b90]No roles configured.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Model Roles",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("Role", style="bold #8db0ff", min_width=8, max_width=16)
    table.add_column("Model", style="bold white", overflow="fold")
    for role, model_id in roles_cfg.items():
        table.add_row(str(role), str(model_id))
    c.print(table)


def render_settings(
    kernel_cfg: dict[str, Any],
    perm_cfg: dict[str, Any],
    out: Console | None = None,
) -> None:
    c = out or console
    table = Table(
        title="◆ Runtime Settings",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("Setting", style="bold #8db0ff", min_width=12, max_width=22)
    table.add_column("Value", style="bold white", min_width=8, max_width=18)
    table.add_column("What it does", style="dim #8b8b90", overflow="fold")
    table.add_row("clarify", str(kernel_cfg.get("clarify", True)), "Pre-turn ambiguity checker")
    table.add_row("max_tool_steps", str(kernel_cfg.get("max_tool_steps", 8)), "Chained tool calls per turn")
    table.add_row("concurrent_slots", str(kernel_cfg.get("concurrent_slots", 4)), "Background task slots")
    table.add_row(
        "skill_autonomy",
        str(perm_cfg.get("skill_autonomy", "suggest_only")),
        "Self-created skill autonomy",
    )
    c.print(table)


def render_sessions(
    rows: list[dict[str, Any]],
    current_id: str = "",
    out: Console | None = None,
) -> None:
    c = out or console
    if not rows:
        c.print("[dim #8b8b90]No saved sessions. This one starts empty.[/dim #8b8b90]")
        return
    table = Table(
        title="◆ Saved Sessions",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("ID", style="dim #8b8b90", min_width=8, max_width=12)
    table.add_column("Updated", style="white", min_width=12, max_width=20)
    table.add_column("Mode", style="bold #00ff00", min_width=6, max_width=12)
    table.add_column("Title", style="white", overflow="fold")
    for row in rows:
        sid = str(row.get("id", ""))
        marker = "● " if sid == current_id else "  "
        table.add_row(
            marker + sid,
            str(row.get("updated_at", ""))[:19].replace("T", " "),
            str(row.get("mode", "")),
            str(row.get("title") or "(untitled)"),
        )
    c.print(table)
    c.print(
        "[dim #8b8b90]/resume to pick one · /resume <id> to load · "
        "/new for a blank conversation[/dim #8b8b90]"
    )


class _LiveStatus:
    """Renderable that re-reads TurnRenderer each Live refresh so the spinner moves."""

    def __init__(self, renderer: "TurnRenderer") -> None:
        self.renderer = renderer

    def __rich_console__(self, _console: Console, _options):
        yield self.renderer._status_renderable()


class TurnRenderer:
    """Live thinking spinner, in-place tool rows, markdown reply, turn footer."""

    def __init__(self, out: Optional[Console] = None) -> None:
        self.console = out or console
        self.streamed_text = ""
        self.think_buffer = ""
        self.start_time = 0.0
        self.tool_count = 0
        self.card_count = 0
        self._active = False
        self._in_tag = False
        self._think_started = 0.0
        self._live: Optional[Live] = None
        self._live_kind: str = ""
        self._think_announced = False
        self._think_closed = False
        self._open_tools: list[dict[str, Any]] = []
        self._tag_rest = ""
        self._pending_block = ""

    def _width(self) -> int:
        return term_cols(self.console)

    def _use_live(self) -> bool:
        try:
            return bool(self.console.is_terminal)
        except Exception:
            return False

    def _running_tool(self) -> dict[str, Any] | None:
        return next((t for t in reversed(self._open_tools) if "done" not in t), None)

    def _status_renderable(self) -> Text:
        elapsed = time.time() - (self._think_started or self.start_time or time.time())
        frame = SPIN[int(elapsed * 10) % len(SPIN)]
        width = self._width()
        if self._live_kind == "think":
            line = Text()
            line.append(f"{frame} ", style="spinner")
            line.append("Thinking… ", style="thought")
            line.append(fmt_duration(elapsed), style="thought_dim")
            return line
        running = self._running_tool()
        if self._live_kind == "tool" and running:
            return _tool_heading(
                running["name"],
                running["args"],
                running["ring"],
                f"running {fmt_duration(time.time() - running['t0'])}",
                width=width,
            )
        return Text("")

    def _start_live(self, kind: str) -> None:
        self._live_kind = kind
        if not self._use_live():
            if kind == "think" and not self._think_announced:
                self.console.print("[thought]Thinking…[/thought]")
                self._think_announced = True
            elif kind == "tool":
                running = self._running_tool()
                if running and not running.get("printed_run"):
                    self.console.print(
                        _tool_heading(
                            running["name"],
                            running["args"],
                            running["ring"],
                            "running",
                            width=self._width(),
                        )
                    )
                    running["printed_run"] = True
            return
        try:
            if self._live is None:
                self._live = Live(
                    _LiveStatus(self),
                    console=self.console,
                    refresh_per_second=10,
                    transient=True,
                    vertical_overflow="crop",
                )
                self._live.start()
            else:
                self._live.update(_LiveStatus(self))
        except Exception:
            self._live = None
            self._live_kind = ""
            if kind == "think" and not self._think_announced:
                self.console.print("[thought]Thinking…[/thought]")
                self._think_announced = True

    def _stop_live(self) -> None:
        live = self._live
        self._live = None
        self._live_kind = ""
        if live is None:
            return
        try:
            live.stop()
        except Exception:
            pass

    def begin_turn(self) -> None:
        self.finish()
        self._active = True
        self.start_time = time.time()
        self._think_started = self.start_time
        self.streamed_text = ""
        self.think_buffer = ""
        self._pending_block = ""
        self._in_tag = False
        self.tool_count = 0
        self.card_count = 0
        self._open_tools = []
        self._tag_rest = ""
        self._think_announced = False
        self._think_closed = False

    def on_thinking(self) -> None:
        if not self._active:
            self.begin_turn()
        if not self._think_announced and not self._think_closed:
            self._start_live("think")
            self._think_announced = True

    def on_token(self, token: str) -> None:
        if not self._active:
            self.begin_turn()
        for kind, piece in self._split_think(token):
            if kind == "think":
                if not self._think_started:
                    self._think_started = time.time()
                self.think_buffer += piece
                if not self._think_announced and not self._think_closed:
                    self._start_live("think")
                    self._think_announced = True
            elif piece:
                if (self.think_buffer or self._think_announced) and not self._think_closed:
                    self._close_think()
                self.streamed_text += piece
                self._pending_block += piece
                blocks, self._pending_block = _extract_completed_blocks(self._pending_block)
                for b in blocks:
                    self.console.print(Markdown(b))

    def on_tool_call(self, tool_name: str, args: dict[str, Any], ring: int = 1) -> None:
        if not self._active:
            self.begin_turn()
        self._close_think()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        self.tool_count += 1
        self._open_tools.append(
            {"name": tool_name, "args": args or {}, "ring": ring, "t0": time.time()}
        )
        self._start_live("tool")
        self._think_closed = False
        self._think_announced = False
        self._think_started = time.time()

    def on_tool_result(self, name: str, result: str = "") -> None:
        self._stop_live()
        started = next((t for t in reversed(self._open_tools) if t["name"] == name and "done" not in t), None)
        elapsed = time.time() - started["t0"] if started else 0.0
        if started:
            started["done"] = True
        ring = int(started["ring"]) if started else 1
        args = started["args"] if started else {}
        width = self._width()
        suffix = f"done {fmt_duration(elapsed)}"
        if (result or "").strip().lower() == "denied":
            suffix = f"denied {fmt_duration(elapsed)}"
        self.console.print(_tool_heading(name, args, ring, suffix, width=width))
        for line in _write_preview(args, result, width):
            self.console.print(line)

    def on_card(self) -> None:
        self._stop_live()
        self.card_count += 1

    def on_stuck(self, question: str) -> None:
        self._close_think()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        self.console.print(
            Panel(
                f"[bold #e0af68]Friday is stuck:[/bold #e0af68] {question}",
                title="needs clarification",
                border_style="#e0af68",
            )
        )

    def on_idle(self) -> None:
        self.finish()

    def finish(self) -> None:
        if not self._active:
            return
        self._close_think()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        elapsed = time.time() - (self.start_time or time.time())
        bits = [f"◆ {fmt_duration(elapsed)}"]
        if self.tool_count:
            bits.append(f"{self.tool_count} tool" + ("s" if self.tool_count != 1 else ""))
        if self.card_count:
            bits.append(f"{self.card_count} card" + ("s" if self.card_count != 1 else ""))
        self.console.print(Rule(style="#404040"))
        self.console.print(f"[footer]{' · '.join(bits)}[/footer]")
        self.console.print()
        self._active = False
        self.streamed_text = ""
        self.think_buffer = ""
        self._in_tag = False
        self._tag_rest = ""
        self._pending_block = ""
        self._think_announced = False
        self._think_closed = False

    def _split_think(self, token: str) -> list[tuple[str, str]]:
        data = self._tag_rest + token
        self._tag_rest = ""
        out: list[tuple[str, str]] = []
        while data:
            if self._in_tag:
                end = data.find("</think>")
                if end == -1:
                    keep, data = _hold_partial_tag(data, "</think>")
                    if keep:
                        out.append(("think", keep))
                    self._tag_rest = data
                    break
                out.append(("think", data[:end]))
                data = data[end + len("</think>") :]
                self._in_tag = False
                continue
            start = data.find("<think>")
            if start == -1:
                keep, data = _hold_partial_tag(data, "<think>")
                if keep:
                    out.append(("text", keep))
                self._tag_rest = data
                break
            if start:
                out.append(("text", data[:start]))
            data = data[start + len("<think>") :]
            self._in_tag = True
        return out

    def _close_think(self) -> None:
        self._stop_live()
        if self._think_closed:
            return
        had = bool(self.think_buffer.strip()) or self._think_announced
        elapsed = time.time() - (self._think_started or self.start_time or time.time())
        if had:
            self.console.print(f"[thought]◆ thought {fmt_duration(elapsed)}[/thought]")
        self.think_buffer = ""
        self._think_started = 0.0
        self._think_announced = False
        self._think_closed = True


def _extract_completed_blocks(buffer: str) -> tuple[list[str], str]:
    """Split buffer into completed Markdown blocks and any incomplete trailing text."""
    blocks: list[str] = []
    rest = buffer
    while rest:
        if rest.startswith("```"):
            end_cb = rest.find("\n```", 3)
            if end_cb != -1:
                after = rest.find("\n", end_cb + 4)
                if after != -1:
                    blocks.append(rest[:after].strip())
                    rest = rest[after + 1 :].lstrip("\n")
                    continue
                tail = rest[end_cb + 4 :]
                if not tail.strip():
                    blocks.append(rest.strip())
                    rest = ""
                    break
            break

        idx = rest.find("\n\n")
        if idx != -1:
            code_start = rest.find("```")
            if code_start != -1 and code_start < idx:
                prefix = rest[:code_start].strip()
                if prefix:
                    blocks.append(prefix)
                rest = rest[code_start:]
                continue
            block = rest[:idx].strip()
            if block:
                blocks.append(block)
            rest = rest[idx + 2 :].lstrip("\n")
            continue

        break

    return blocks, rest


def _hold_partial_tag(data: str, tag: str) -> tuple[str, str]:
    """If data ends with a prefix of tag, hold it back; else emit all."""
    for i in range(1, len(tag)):
        if data.endswith(tag[:i]):
            return data[:-i], data[-i:]
    return data, ""
