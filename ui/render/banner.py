"""Launch banner."""

from __future__ import annotations

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ui.render.theme import console, term_cols

# Block-art "F": U+2588 only (Cascadia/Consolas safe). All rows equal width.
# Braille art was dropped: uneven rows + missing glyphs on Windows conhost.
FRIDAY_BRAILLE_LOGO = [
    " ██████ ",
    " █      ",
    " █████  ",
    " █      ",
    " █      ",
]


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
        logo_text = Text("\n".join(FRIDAY_BRAILLE_LOGO), style="bold #e0af68", no_wrap=True)
        card_grid = Table.grid(expand=True, padding=(0, 2))
        card_grid.add_column(width=12, justify="center", no_wrap=True)
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
