"""Live turn renderer: thinking spinner, in-place tool rows, markdown reply."""

from __future__ import annotations

import time
from typing import Any, Optional

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from ui.render.theme import SPIN, console, fmt_duration, ring_label, term_cols


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


def tool_heading(
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
    line.append_text(Text.from_markup(ring_label(ring)))
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


def _thought_preview(text: str, max_chars: int = 400) -> str:
    """Single-line collapsed preview so reasoning stays one tidy row."""
    collapsed = " ".join(text.split())
    if len(collapsed) > max_chars:
        collapsed = collapsed[: max_chars - 1] + "…"
    return collapsed


def write_preview(args: dict[str, Any], result: str, width: int) -> list[Text]:
    """Short files-write result + snippet only. Other tools stay a single
    heading row (spec: only `files` writes show a content preview)."""
    lines: list[Text] = []
    inner = max(16, width - 10)
    action = str(args.get("action") or "")
    content = str(args.get("content") or "")
    if action == "write":
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
            extra = sum(1 for t in self._open_tools if "done" not in t) - 1
            suffix = f"running {fmt_duration(time.time() - running['t0'])}"
            if extra > 0:
                suffix += f" +{extra}"
            return tool_heading(
                running["name"],
                running["args"],
                running["ring"],
                suffix,
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
                        tool_heading(
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

    def on_tool_call(
        self, tool_name: str, args: dict[str, Any], ring: int = 1, call_id: str = ""
    ) -> None:
        if not self._active:
            self.begin_turn()
        self._close_think()
        if self._pending_block.strip():
            self.console.print(Markdown(self._pending_block.strip()))
            self._pending_block = ""
        self.tool_count += 1
        self._open_tools.append(
            {
                "name": tool_name,
                "args": args or {},
                "ring": ring,
                "t0": time.time(),
                "id": call_id,
            }
        )
        self._start_live("tool")
        self._think_closed = False
        self._think_announced = False
        self._think_started = time.time()

    def on_tool_result(self, name: str, result: str = "", call_id: str = "") -> None:
        self._stop_live()
        started = None
        if call_id:
            started = next(
                (t for t in self._open_tools if t.get("id") == call_id and "done" not in t),
                None,
            )
        if started is None:
            started = next(
                (t for t in self._open_tools if t["name"] == name and "done" not in t),
                None,
            )
        elapsed = time.time() - started["t0"] if started else 0.0
        if started:
            started["done"] = True
        ring = int(started["ring"]) if started else 1
        args = started["args"] if started else {}
        width = self._width()
        suffix = f"done {fmt_duration(elapsed)}"
        if (result or "").strip().lower() == "denied":
            suffix = f"denied {fmt_duration(elapsed)}"
        self.console.print(tool_heading(name, args, ring, suffix, width=width))
        for line in write_preview(args, result, width):
            self.console.print(line)
        if any("done" not in t for t in self._open_tools):
            self._start_live("tool")

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
        self.console.print()
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
        raw = self.think_buffer.strip()
        elapsed = time.time() - (self._think_started or self.start_time or time.time())
        if raw:
            # Text (not markup) so brackets in reasoning can't inject styles.
            line = Text()
            line.append(f"◆ thought {fmt_duration(elapsed)}", style="thought")
            preview = _thought_preview(raw)
            if preview:
                line.append(f"  {preview}", style="thought_dim")
            self.console.print(line)
        elif self._think_announced:
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
