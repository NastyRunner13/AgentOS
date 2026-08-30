"""Interactive menus and dialogs for Friday CLI."""

from __future__ import annotations

from typing import Any, Optional
from rich.panel import Panel
from rich.table import Table
from tools.specs import SPECS
from ui.renderer import console, render_sessions

MODES = {
    "Code": "Full coding autonomy with shell, file edits, and test verification.",
    "Architect": "Planning and design mode: inspects repo, drafts architecture specs without mutating files.",
    "Ask": "Q&A and explanation mode: read-only tools, no host execution.",
    "Fast": "Uses fast/cheap models for quick one-off answers and edits.",
}


async def pick_session(rows: list[dict[str, Any]], current_id: str = "") -> str | None:
    """Interactive session picker. Esc / cancel returns None."""
    if not rows:
        return None
    try:
        from prompt_toolkit.shortcuts import radiolist_dialog
    except Exception:
        render_sessions(rows, current_id)
        return None
    values = []
    for row in rows:
        sid = str(row.get("id", ""))
        title = str(row.get("title") or "(untitled)")
        updated = str(row.get("updated_at") or "")[:16].replace("T", " ")
        mark = "● " if sid == current_id else "  "
        values.append((sid, f"{mark}{sid}  {updated}  {title}"))
    try:
        return await radiolist_dialog(
            title="Resume session",
            text="Select a conversation. Esc cancels.",
            values=values,
        ).run_async()
    except Exception:
        render_sessions(rows, current_id)
        return None


def show_mode_dialog(current_mode: str = "Code") -> str:
    """Displays available modes and allows selection."""
    table = Table(title="🎯 Agent Modes", border_style="cyan", header_style="bold cyan")
    table.add_column("Mode", style="bold white", width=12)
    table.add_column("Description", style="white")
    table.add_column("Active", style="bold green", width=8, justify="center")

    for m, desc in MODES.items():
        is_active = "●" if m.lower() == current_mode.lower() else ""
        table.add_row(m, desc, is_active)

    console.print(table)
    console.print("[dim]Usage: [bold white]/mode <name>[/bold white] (e.g. /mode code, /mode architect, /mode ask)[/dim]")
    return current_mode


def show_provider_dialog(models_cfg: dict[str, Any]) -> None:
    """Displays configured providers and default models."""
    providers = models_cfg.get("providers") or {}
    default_p = models_cfg.get("default_provider", "openrouter")
    
    table = Table(title="🔌 Configured LLM Providers", border_style="blue", header_style="bold blue")
    table.add_column("Provider", style="bold white", width=16)
    table.add_column("Kind", style="cyan", width=12)
    table.add_column("API Key Env", style="dim", width=24)
    table.add_column("Default", style="bold green", width=8, justify="center")

    for name, pcfg in providers.items():
        is_default = "●" if name == default_p else ""
        table.add_row(
            name,
            pcfg.get("kind", "openrouter"),
            pcfg.get("api_key_env", "N/A"),
            is_default,
        )

    console.print(table)
    console.print("[dim]Edit [bold white]config/models.yaml[/bold white] and run [bold white]/reload[/bold white] to change active provider.[/dim]")


def show_skills_dialog(root_path: Any = None) -> None:
    """Displays available skills and procedures from global and workspace directories."""
    from pathlib import Path
    from brain.skills import load_skills

    r_path = Path(root_path) if root_path else None
    skills = load_skills(r_path)

    table = Table(title="✨ Agent Skills & Procedural Memory", border_style="green", header_style="bold green")
    table.add_column("Skill Name", style="bold white", width=22)
    table.add_column("Source", style="cyan", width=12)
    table.add_column("Description", style="dim")

    if not skills:
        table.add_row("self-distill", "Built-in", "Automatic skill suggestion after 3+ step novel trajectories")
        table.add_row("librarian-sync", "Built-in", "Background fact distillation from L2 episodic logs")
    else:
        for s in skills:
            table.add_row(s.name, s.source, s.description)

    console.print(table)
    global_dir_str = (Path.home() / ".agents" / "skills").as_posix()
    console.print(
        f"[dim]Run with [bold white]/<name>[/bold white] or [bold white]/skill <name>[/bold white]. "
        f"Loaded from [bold white]{global_dir_str}[/bold white] and [bold white]skills/<name>/SKILL.md[/bold white].[/dim]"
    )


def show_plugins_dialog() -> None:
    """Displays active native tools and plugin specs."""
    table = Table(title="🧩 Tools & Native Integrations", border_style="magenta", header_style="bold magenta")
    table.add_column("Tool Name", style="bold white", width=16)
    table.add_column("Ring", style="bold", width=8, justify="center")
    table.add_column("Description", style="white")

    ring_styles = {
        0: "[green]0 (Safe)[/green]",
        1: "[yellow]1 (Read)[/yellow]",
        2: "[bold red]2 (Card)[/bold red]",
    }

    ring_map = {
        "files": 1,
        "shell": 2,
        "browser": 2,
        "computer": 2,
        "kb_propose": 0,
        "task_spawn": 1,
        "task_steer": 1,
    }

    for spec in SPECS:
        name = spec.get("name", "")
        desc = spec.get("description", "")
        ring = ring_map.get(name, 1)
        table.add_row(name, ring_styles.get(ring, str(ring)), desc[:70] + "..." if len(desc) > 70 else desc)

    console.print(table)
