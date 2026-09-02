"""Interactive menus and dialogs for the Friday CLI."""

from __future__ import annotations

from typing import Any
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
    """Print the session list and read an id. Avoids a full-screen dialog that
    fights the print-loop transcript on Windows."""
    if not rows:
        return None
    render_sessions(rows, current_id)
    try:
        from prompt_toolkit import PromptSession
        raw = await PromptSession().prompt_async("session id: ")
    except (EOFError, KeyboardInterrupt, Exception):
        return None
    needle = str(raw or "").strip()
    if not needle:
        return None
    for row in rows:
        sid = str(row.get("id", ""))
        title = str(row.get("title") or "")
        if sid == needle or sid.startswith(needle) or needle.lower() in title.lower():
            return sid
    return None


def show_shortcuts_dialog() -> None:
    """Keyboard shortcuts grouped by AgentOS surface."""
    groups = [
        (
            "Essentials",
            [
                ("Send prompt", "Enter"),
                ("Cancel current turn", "Ctrl+C"),
                ("Cycle mode (Code / Architect / Ask / Fast)", "Shift+Tab"),
                ("Keyboard shortcuts palette", "Ctrl+X / /shortcuts"),
                ("Command reference / help", "/help"),
                ("Exit / quit Friday", "Ctrl+Q / Ctrl+D / /exit"),
            ],
        ),
        (
            "Input & Editing",
            [
                ("Insert newline in composer", "Ctrl+J"),
                ("Attach a workspace file", "@path (Tab to complete)"),
                ("Clear terminal screen", "/clear"),
                ("Rename active session", "/rename <title>"),
            ],
        ),
        (
            "AgentOS Memory & Tools",
            [
                ("Confirmed long-term facts (L2)", "/facts"),
                ("Pending Librarian proposals", "/proposals"),
                ("Trigger Librarian consolidation draft", "/consolidate"),
                ("Approve permission card or memory proposal", "/approve <id> / /approve all"),
                ("Deny permission card or proposal", "/deny <id>"),
                ("Background task manager", "/tasks"),
                ("Steer running background task", "/steer <id> <text>"),
                ("Spawn background task", "/task <title> <prompt>"),
                ("Voice push-to-talk or inject text", "/listen [text]"),
                ("Hide or show the voice orb", "/orb"),
            ],
        ),
        (
            "Runtime & Dial Control",
            [
                ("Switch active agent mode", "/mode [name]"),
                ("Configure LLM providers", "/provider"),
                ("Procedural skills memory", "/skills · /skill <name>"),
                ("Registered tool & ring permissions", "/plugins"),
                ("Runtime settings (clarify, slots, etc.)", "/settings"),
                ("Reload YAML configs without restart", "/reload"),
                ("Saved session browser", "/sessions · /resume [id]"),
                ("Start clean session", "/new"),
            ],
        ),
    ]

    table = Table(
        title="◆ Keyboard Shortcuts & Command Palette",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("Action", style="white", ratio=3)
    table.add_column("Keys / Command", style="bold #8db0ff", ratio=2, justify="right")

    for grp_name, items in groups:
        table.add_row(f"[bold #e0af68]◆ {grp_name}[/bold #e0af68]", "")
        for action, keys in items:
            table.add_row(f"  [dim]›[/dim] {action}", f"[bold white]{keys}[/bold white]")
        table.add_row("", "")

    console.print(table)
    console.print("[dim #8b8b90]Press [bold white]Ctrl+X[/bold white] anytime to view this shortcuts palette.[/dim #8b8b90]\n")


def show_mode_dialog(current_mode: str = "Code") -> str:
    """Available agent modes."""
    table = Table(title="◆ Agent Modes", border_style="#505050", header_style="bold #e0af68", expand=True)
    table.add_column("Mode", style="bold white", min_width=8, max_width=12)
    table.add_column("Description", style="white", overflow="fold")
    table.add_column("Active", style="bold #00ff00", min_width=6, justify="center")

    for m, desc in MODES.items():
        is_active = "●" if m.lower() == current_mode.lower() else ""
        table.add_row(m, desc, is_active)

    console.print(table)
    console.print("[dim #8b8b90]Usage: [bold white]/mode <name>[/bold white] (e.g. /mode code, /mode architect, /mode ask, /mode fast)[/dim #8b8b90]")
    return current_mode


def show_provider_dialog(models_cfg: dict[str, Any]) -> None:
    """Displays configured providers and default models."""
    providers = models_cfg.get("providers") or {}
    default_p = models_cfg.get("default_provider", "openrouter")

    table = Table(title="◆ Configured LLM Providers", border_style="#505050", header_style="bold #e0af68", expand=True)
    table.add_column("Provider", style="bold white", min_width=10, max_width=18)
    table.add_column("Kind", style="bold #8db0ff", min_width=8, max_width=14)
    table.add_column("API Key Env", style="dim #8b8b90", overflow="fold")
    table.add_column("Default", style="bold #00ff00", min_width=6, justify="center")

    for name, pcfg in providers.items():
        is_default = "●" if name == default_p else ""
        table.add_row(
            name,
            pcfg.get("kind", "openrouter"),
            pcfg.get("api_key_env", "N/A"),
            is_default,
        )

    console.print(table)
    console.print("[dim #8b8b90]Edit [bold white]config/models.yaml[/bold white] and run [bold white]/reload[/bold white] to apply changes.[/dim #8b8b90]")


def show_skills_dialog(root_path: Any = None) -> None:
    """Displays available skills and procedures from global and workspace directories."""
    from pathlib import Path
    from brain.skills import load_skills

    r_path = Path(root_path) if root_path else None
    skills = load_skills(r_path)

    table = Table(title="◆ Agent Skills & Procedural Memory", border_style="#505050", header_style="bold #e0af68", expand=True)
    table.add_column("Skill Name", style="bold white", min_width=10, max_width=22)
    table.add_column("Source", style="bold #8db0ff", min_width=8, max_width=14)
    table.add_column("Description", style="dim #8b8b90", overflow="fold")

    if not skills:
        table.add_row("self-distill", "Built-in", "Automatic skill suggestion after 3+ step novel trajectories")
        table.add_row("librarian-sync", "Built-in", "Background fact distillation from L2 episodic logs")
    else:
        for s in skills:
            table.add_row(s.name, s.source, s.description)

    console.print(table)
    global_dir_str = (Path.home() / ".agents" / "skills").as_posix()
    console.print(
        f"[dim #8b8b90]Run with [bold white]/<name>[/bold white] or [bold white]/skill <name>[/bold white]. "
        f"Loaded from [bold white]{global_dir_str}[/bold white] and [bold white]skills/<name>/SKILL.md[/bold white].[/dim #8b8b90]"
    )


def show_plugins_dialog(gate: Any = None) -> None:
    """Native tools and their typical permission ring (from Gate.classify)."""
    table = Table(
        title="◆ Tools & Native Integrations",
        border_style="#505050",
        header_style="bold #e0af68",
        expand=True,
    )
    table.add_column("Tool", style="bold white", min_width=10, max_width=18)
    table.add_column("Ring", style="bold", min_width=10, justify="center")
    table.add_column("Description", style="white", overflow="fold")

    ring_styles = {
        0: "[bold #00ff00]0 silent[/bold #00ff00]",
        1: "[bold #e0af68]1 silent[/bold #e0af68]",
        2: "[bold #f38ba8]2 card[/bold #f38ba8]",
        3: "[bold #f38ba8]3 card[/bold #f38ba8]",
    }
    samples = {
        "files": {"action": "read", "path": "."},
        "shell": {"command": ""},
        "browser": {"action": "snapshot"},
        "computer": {"action": "snapshot"},
        "web_search": {"query": ""},
        "web_fetch": {"url": "https://example.com"},
        "skill": {"name": ""},
        "kb_read": {"query": ""},
        "kb_propose": {"kind": "fact"},
        "kb_consolidate": {},
        "spawn_task": {"title": "t", "prompt": "p"},
        "ask_user": {"question": "", "options": []},
    }

    for spec in SPECS:
        fn = spec.get("function") or spec
        name = str(fn.get("name", ""))
        desc = str(fn.get("description", ""))
        if gate is not None and hasattr(gate, "classify"):
            ring = int(gate.classify(name, samples.get(name, {})))
            ring_label = ring_styles.get(ring, str(ring))
            if name == "files":
                ring_label = "[dim]read 0 · write 1 · delete 2+[/dim]"
            elif name == "shell":
                ring_label = "[dim]allowlist 1 · other 2[/dim]"
        else:
            ring_label = "—"
        table.add_row(name, ring_label, desc)

    console.print(table)
    console.print(
        "[dim #8b8b90]Ring 0–1 run silent. Ring 2–3 raise a [bold white]card[/bold white] "
        "and wait for y/n or /approve.[/dim #8b8b90]"
    )

