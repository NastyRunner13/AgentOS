"""Transcript tables: facts, proposals, tasks, sessions, plans, settings."""

from __future__ import annotations

from typing import Any

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ui.render.theme import console, term_cols
from ui.render.turn import tool_heading


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
    # No leading blank: TurnRenderer.finish() already leaves one, so a new
    # turn gets exactly one gap instead of two stacking up.
    c = out or console
    line = Text()
    line.append("❯ ", style="bold #8db0ff")
    line.append(text, style="white")
    c.print(line)


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
    console.print(tool_heading(tool_name, args, ring, "running", width=term_cols()))


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
