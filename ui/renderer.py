"""Rich console rendering for the Friday CLI transcript."""

from __future__ import annotations

import time
from typing import Any, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

FRIDAY_THEME = Theme(
    {
        "info": "dim cyan",
        "warning": "yellow",
        "error": "bold red",
        "success": "bold green",
        "thought": "italic #7f849c",
        "tool": "cyan",
        "ring0": "green",
        "ring1": "yellow",
        "ring2": "bold red",
        "banner": "bold cyan",
        "you": "bold blue",
        "footer": "dim",
        "spinner": "bold cyan",
        "tool_ok": "bold green",
        "tool_run": "bold yellow",
        "tool_fail": "bold red",
        "gutter": "dim cyan",
        "rule": "dim",
    }
)

console = Console(theme=FRIDAY_THEME)

RING_STYLE = {0: "ring0", 1: "ring1", 2: "ring2", 3: "ring2"}
TOOL_HINT = {
    "shell": "sh",
    "files": "file",
    "browser": "web",
    "computer": "os",
    "kb_propose": "kb",
    "kb_read": "kb",
    "kb_consolidate": "kb",
    "spawn_task": "task",
}

TOOL_ICON = {
    "shell": "⚡",
    "files": "📄",
    "browser": "🌐",
    "computer": "🖥",
    "kb_propose": "📝",
    "kb_read": "📖",
    "kb_consolidate": "📚",
    "spawn_task": "🚀",
}


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
        text = " ".join(f"{k}={v}" for k, v in list(args.items())[:3])
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _tool_heading(name: str, args: dict[str, Any], ring: int, suffix: str = "") -> Text:
    icon = TOOL_ICON.get(name, "⚙")
    # Determine status icon and style from suffix
    if suffix.startswith("done"):
        status_icon = "✓"
        status_style = "tool_ok"
    elif suffix == "running":
        status_icon = "⏳"
        status_style = "tool_run"
    else:
        status_icon = "›"
        status_style = "dim"
    line = Text("  ")
    line.append(f"{icon} ", style=status_style)
    line.append(TOOL_HINT.get(name, "fn"), style="tool")
    line.append("  ")
    line.append(name, style="bold")
    summary = _short_args(args)
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
    """Format a tool result preview with a left-border gutter."""
    preview = " ".join(text.split())
    if len(preview) > width:
        preview = preview[: width - 1] + "…"
    line = Text("    │ ", style="gutter")
    line.append(preview, style="dim")
    return line


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
    c = out or console
    grid = Table.grid(expand=True)
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="right", ratio=1)
    left = Text()
    left.append("Friday", style="bold cyan")
    left.append("  AgentOS", style="dim")
    if cwd:
        left.append("  ")
        left.append(cwd, style="bold white")
    if branch:
        left.append("  ")
        left.append(branch, style="green")
    right = f"[dim]{model}[/dim]  [green]{mode}[/green]"
    grid.add_row(left, right)
    meta = Text()
    if session_id:
        meta.append("session ", style="dim")
        meta.append(session_id, style="bold")
    if title:
        if session_id:
            meta.append("  ·  ", style="dim")
        meta.append(title, style="dim")
    body: Any = Group(grid, meta) if meta.plain else grid
    c.print(Panel(body, border_style="cyan", padding=(0, 1)))
    c.print("[dim]/new  /resume  /exit  /help  ·  type / for commands and skills[/dim]\n")


def display_user_content(content: str) -> str:
    """Collapse a stored skill turn back to `/name args` for the transcript."""
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
            c.print("[banner]friday[/banner]")
            c.print(Markdown(content))
            c.print()


def render_user(text: str, out: Console | None = None) -> None:
    c = out or console
    c.print()
    c.print("[you]you[/you]")
    c.print(text)


def render_card(ev: dict[str, Any], out: Console | None = None) -> None:
    c = out or console
    cid = ev.get("id", "unknown")
    ring = ev.get("ring", 2)
    action = ev.get("action_preview", "")
    reason = ev.get("reason", "Host mutation requires permission")
    body = Text()
    body.append(str(action) + "\n", style="bold")
    body.append(str(reason), style="dim")
    body.append("\n\n")
    body.append("y allow", style="bold green")
    body.append("   ", style="dim")
    body.append("n deny", style="bold red")
    body.append(f"   /approve {cid}  /deny {cid}", style="dim")
    c.print(
        Panel(
            body,
            title=f"card {cid}  ·  ring {ring}",
            border_style="red" if int(ring) >= 2 else "yellow",
            padding=(0, 1),
        )
    )


def render_tool_call(tool_name: str, args: dict[str, Any], ring: int = 1) -> None:
    console.print(_tool_heading(tool_name, args, ring, "running"))


def render_facts(facts: list[dict[str, Any]]) -> None:
    if not facts:
        console.print("[dim]No confirmed long-term facts in memory.[/dim]")
        return
    table = Table(title="Confirmed facts", border_style="cyan", header_style="bold cyan")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Fact", style="white")
    table.add_column("Confidence", style="green", width=12, justify="center")
    for f in facts:
        conf = f.get("confidence", 1.0)
        table.add_row(
            str(f.get("id", "")),
            str(f.get("statement", "")),
            f"{conf:.0%}" if isinstance(conf, (int, float)) else str(conf),
        )
    console.print(table)


def render_proposals(proposals: list[dict[str, Any]]) -> None:
    if not proposals:
        console.print("[dim]No pending Librarian proposals.[/dim]")
        return
    table = Table(title="Pending proposals", border_style="yellow", header_style="bold yellow")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Kind", style="magenta", width=12)
    table.add_column("Preview", style="white")
    for p in proposals:
        payload = p.get("payload", {})
        preview = payload.get("statement") or payload.get("name") or str(payload)
        table.add_row(str(p.get("id", "")), str(p.get("kind", "")), str(preview))
    console.print(table)
    console.print("[dim]Approve with /approve <id> or /approve all[/dim]")


def render_tasks(tasks: list[Any]) -> None:
    if not tasks:
        console.print("[dim]No tasks in queue.[/dim]")
        return
    table = Table(title="Tasks", border_style="blue", header_style="bold blue")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Status", style="bold", width=14)
    table.add_column("Title", style="white")
    status_styles = {
        "running": "[bold green]running[/bold green]",
        "queued": "[yellow]queued[/yellow]",
        "done": "[dim]done[/dim]",
        "failed": "[bold red]failed[/bold red]",
        "stuck": "[bold yellow]stuck[/bold yellow]",
        "waiting_approval": "[bold red]card[/bold red]",
    }
    for t in tasks:
        st = getattr(t, "status", "unknown")
        table.add_row(str(getattr(t, "id", "")), status_styles.get(st, st), str(getattr(t, "title", "")))
    console.print(table)


def render_roles(roles_cfg: dict[str, Any]) -> None:
    if not roles_cfg:
        console.print("[dim]No roles configured.[/dim]")
        return
    table = Table(title="Model roles", border_style="magenta", header_style="bold magenta")
    table.add_column("Role", style="cyan", width=15)
    table.add_column("Model", style="bold white")
    for role, model_id in roles_cfg.items():
        table.add_row(str(role), str(model_id))
    console.print(table)


def render_settings(kernel_cfg: dict[str, Any], perm_cfg: dict[str, Any]) -> None:
    table = Table(title="Runtime settings", border_style="cyan", header_style="bold cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="bold white")
    table.add_column("What it does", style="dim")
    table.add_row("clarify", str(kernel_cfg.get("clarify", True)), "Pre-turn ambiguity checker")
    table.add_row("max_tool_steps", str(kernel_cfg.get("max_tool_steps", 8)), "Chained tool calls per turn")
    table.add_row("concurrent_slots", str(kernel_cfg.get("concurrent_slots", 4)), "Background task slots")
    table.add_row("skill_autonomy", str(perm_cfg.get("skill_autonomy", "suggest_only")), "Self-created skill autonomy")
    console.print(table)


def render_sessions(rows: list[dict[str, Any]], current_id: str = "") -> None:
    if not rows:
        console.print("[dim]No saved sessions. This one starts empty.[/dim]")
        return
    table = Table(title="Sessions", border_style="cyan", header_style="bold cyan")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Updated", style="white", width=20)
    table.add_column("Mode", style="green", width=10)
    table.add_column("Title", style="white")
    for row in rows:
        sid = str(row.get("id", ""))
        marker = "● " if sid == current_id else "  "
        table.add_row(
            marker + sid,
            str(row.get("updated_at", ""))[:19].replace("T", " "),
            str(row.get("mode", "")),
            str(row.get("title") or "(untitled)"),
        )
    console.print(table)
    console.print("[dim]/resume to pick one · /resume <id> to load · /new for a blank conversation[/dim]")


class TurnRenderer:
    """Thinking accordion, tool rows, markdown reply, turn footer."""

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
        self._open_tools: list[dict[str, Any]] = []
        self._tag_rest = ""
        self._pending_block = ""

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
        self._open_think()

    def on_thinking(self) -> None:
        if not self._active:
            self.begin_turn()
        elif not self._live_kind:
            self._open_think()

    def on_token(self, token: str) -> None:
        if not self._active:
            self.begin_turn()
        for kind, piece in self._split_think(token):
            if kind == "think":
                if self._live_kind != "think" and not self.think_buffer:
                    if not self._think_started:
                        self._think_started = time.time()
                    self._open_think()
                self.think_buffer += piece
                self._paint_think()
            elif piece:
                if self.think_buffer or self._live_kind == "think":
                    self._close_think()
                self.streamed_text += piece
                self._pending_block += piece
                blocks, self._pending_block = _extract_completed_blocks(self._pending_block)
                if blocks:
                    self._stop_live()
                    for b in blocks:
                        self.console.print(Markdown(b))
                if self._pending_block.strip():
                    self._paint_draft(self._pending_block)

    def on_tool_call(self, tool_name: str, args: dict[str, Any], ring: int = 1) -> None:
        if not self._active:
            self.begin_turn()
        self._close_think()
        self._stop_live()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        self.tool_count += 1
        self._open_tools.append({"name": tool_name, "args": args, "ring": ring, "t0": time.time()})
        self.console.print(_tool_heading(tool_name, args, ring, "running"))

    def on_tool_result(self, name: str, result: str = "") -> None:
        started = next((t for t in reversed(self._open_tools) if t["name"] == name and "done" not in t), None)
        elapsed = time.time() - started["t0"] if started else 0.0
        if started:
            started["done"] = True
        ring = int(started["ring"]) if started else 1
        args = started["args"] if started else {}
        self.console.print(_tool_heading(name, args, ring, f"done {fmt_duration(elapsed)}"))
        preview = " ".join((result or "").split())
        if preview:
            self.console.print(_gutter_preview(preview))

    def on_card(self) -> None:
        self.card_count += 1

    def on_stuck(self, question: str) -> None:
        self.console.print(
            Panel(
                f"[bold yellow]Friday is stuck:[/bold yellow] {question}",
                title="needs clarification",
                border_style="yellow",
            )
        )

    def on_idle(self) -> None:
        self.finish()

    def finish(self) -> None:
        if not self._active:
            self._stop_live()
            return
        self._close_think()
        self._stop_live()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        elapsed = time.time() - (self.start_time or time.time())
        bits = [fmt_duration(elapsed)]
        if self.tool_count:
            bits.append(f"{self.tool_count} tool" + ("s" if self.tool_count != 1 else ""))
        if self.card_count:
            bits.append(f"{self.card_count} card" + ("s" if self.card_count != 1 else ""))
        self.console.print(Rule(style="rule"))
        self.console.print(f"[footer]{' · '.join(bits)}[/footer]")
        self.console.print()
        self._active = False
        self.streamed_text = ""
        self.think_buffer = ""
        self._in_tag = False
        self._tag_rest = ""
        self._pending_block = ""

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
                data = data[end + len("</think>"):]
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
            data = data[start + len("<think>"):]
            self._in_tag = True
        return out

    def _open_think(self) -> None:
        if self._live_kind == "think":
            return
        self._stop_live()
        body = self._think_renderable()
        if self._start_live(body, kind="think", transient=True):
            return
        if not self._think_announced:
            self.console.print("[thought]thinking[/thought]")
            self._think_announced = True

    def _paint_think(self) -> None:
        if self._live_kind == "think" and self._live:
            self._live.update(self._think_renderable())
        elif self.console.is_terminal and not self._live:
            self.console.print(Text(self.think_buffer[-80:], style="thought"), end="\r")

    def _close_think(self) -> None:
        had = bool(self.think_buffer.strip())
        elapsed = time.time() - (self._think_started or self.start_time or time.time())
        think_live = self._live_kind == "think"
        if think_live:
            self._stop_live()
        if had:
            self.console.print(f"[thought]💭 thought {fmt_duration(elapsed)}[/thought]")
        self.think_buffer = ""
        self._think_started = 0.0
        self._think_announced = False

    def _think_renderable(self) -> Group:
        elapsed = time.time() - (self._think_started or self.start_time or time.time())
        header = Text()
        header.append("⠋ ", style="spinner")
        header.append(f"thinking {fmt_duration(elapsed)}", style="thought")
        # Show last ~4 lines of think buffer for context
        tail = self.think_buffer[-600:] if self.think_buffer else "…"
        lines = tail.split("\n")
        if len(lines) > 4:
            lines = lines[-4:]
        body = Text("\n".join(lines), style="thought")
        return Group(header, body)

    def _paint_draft(self, text: str) -> None:
        md = Markdown(text)
        if self._live_kind == "draft" and self._live:
            self._live.update(md)
            return
        if self._start_live(md, kind="draft", transient=True):
            return

    def _start_live(self, renderable: Any, *, kind: str, transient: bool) -> bool:
        if not self.console.is_terminal:
            return False
        self._stop_live()
        try:
            self._live = Live(
                renderable,
                console=self.console,
                refresh_per_second=8,
                transient=transient,
                vertical_overflow="crop",
            )
            self._live.start()
            self._live_kind = kind
            return True
        except Exception:
            self._live = None
            self._live_kind = ""
            return False

    def _stop_live(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        self._live_kind = ""


def _extract_completed_blocks(buffer: str) -> tuple[list[str], str]:
    """Split buffer into completed Markdown blocks (paragraphs, headers, code blocks)
    and any incomplete trailing text."""
    blocks: list[str] = []
    rest = buffer
    while rest:
        # Check if we are inside a code block
        if rest.startswith("```"):
            end_cb = rest.find("\n```", 3)
            if end_cb != -1:
                after = rest.find("\n", end_cb + 4)
                if after != -1:
                    blocks.append(rest[:after].strip())
                    rest = rest[after + 1:].lstrip("\n")
                    continue
                else:
                    tail = rest[end_cb + 4:]
                    if not tail.strip():
                        blocks.append(rest.strip())
                        rest = ""
                        break
            break

        # Check for paragraph boundary \n\n
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
            rest = rest[idx + 2:].lstrip("\n")
            continue

        break

    return blocks, rest


def _hold_partial_tag(data: str, tag: str) -> tuple[str, str]:
    """If data ends with a prefix of tag, hold it back; else emit all."""
    for i in range(1, len(tag)):
        if data.endswith(tag[:i]):
            return data[:-i], data[-i:]
    return data, ""
