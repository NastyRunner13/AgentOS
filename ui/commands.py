"""Slash-command spec, help text, and handlers. Completer reads the same tables."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable

from ui.render.theme import console

if TYPE_CHECKING:
    from ui.cli import Cli

Handler = Callable[["Cli", str], Awaitable[str | None]]

HELP = """\
[bold #e0af68]◆ Friday Commands & Shortcuts[/bold #e0af68]
  [bold white]/new[/bold white]                   Fresh conversation (saves the current one)
  [bold white]/resume [id][/bold white]           Pick a session, or load one by id
  [bold white]/sessions[/bold white]              List saved conversations
  [bold white]/rename <title>[/bold white]        Name the current session
  [bold white]/shortcuts[/bold white]             Full keyboard shortcuts & command palette (Ctrl+X)
  [bold white]/plan [id][/bold white]             Show waiting plan, latest, or a saved id
  [bold white]/plans[/bold white]                 List saved Architect plans
  [bold white]@path[/bold white]                  Attach a workspace file (Tab completes)
  [bold white]/help[/bold white]                  This cheatsheet
  [bold white]/mode [name][/bold white]           Code, Architect, Ask, Fast
  [bold white]/provider[/bold white]              Configured LLM providers
  [bold white]/skills[/bold white]                Active skills
  [bold white]/skill <name> [args][/bold white]   Run a skill (also /<name>)
  [bold white]/plugins[/bold white]               Tools & ring specifications
  [bold white]/settings[/bold white]              Runtime dials (clarify, slots, etc.)
  [bold white]/listen [text][/bold white]         Push-to-talk (Enter to stop), or inject text
  [bold white]/orb[/bold white]                   Hide or show the voice orb
  [bold white]/task <title> <prompt>[/bold white] Background turn (steer-able)
  [bold white]/steer <id> <text>[/bold white]     Inject guidance into a running task
  [bold white]/tasks[/bold white]                 Running and queued tasks
  [bold white]/approve <id> [id...][/bold white]  Allow a card or memory proposal
  [bold white]/approve all[/bold white]           Bulk-approve pending proposals
  [bold white]/deny <id> [id...][/bold white]     Deny a card or proposal
  [bold white]/facts[/bold white]                 Confirmed long-term facts
  [bold white]/proposals[/bold white]             Pending Librarian drafts
  [bold white]/consolidate[/bold white]           Librarian consolidation draft
  [bold white]/roles[/bold white]                 Model role assignments
  [bold white]/clear[/bold white]                 Clear the screen
  [bold white]/reload[/bold white]                Reread YAML configs without restart
  [bold white]/exit[/bold white]                  Stop the CLI (alias /quit)
"""

SLASH_COMMANDS: dict[str, str] = {
    "/new": "Start a fresh conversation (saves the current one)",
    "/reset": "Alias for /new",
    "/resume": "Resume a previous session: /resume [id]",
    "/sessions": "List saved conversations",
    "/rename": "Rename the current session: /rename <title>",
    "/mode": "Switch agent mode (Code, Architect, Ask, Fast)",
    "/provider": "Select LLM provider & default model",
    "/skills": "Browse available agent skills & procedures",
    "/skill": "Run a skill: /skill <name> [args] (also /<name>)",
    "/plugins": "View active tool specs & integrations",
    "/settings": "Adjust runtime parameters (clarify, max steps, slots)",
    "/shortcuts": "View keyboard shortcuts & command palette (Ctrl+X)",
    "/keys": "Alias for /shortcuts",
    "/plan": "View waiting plan, latest, or /plan <id>",
    "/plans": "List saved Architect plans",
    "/facts": "View confirmed long-term memory facts",
    "/proposals": "View pending Librarian memory proposals",
    "/consolidate": "Trigger Librarian consolidation draft",
    "/listen": "Push-to-talk, or /listen <text> to inject a transcript",
    "/orb": "Hide or show the voice orb",
    "/task": "Spawn background task: /task <title> <prompt>",
    "/steer": "Inject steer into running task: /steer <id> <text>",
    "/tasks": "List running and queued background tasks",
    "/approve": "Approve permission card or memory proposal: /approve <id>",
    "/approve all": "Bulk-approve all pending memory proposals",
    "/deny": "Deny permission card or memory proposal: /deny <id>",
    "/roles": "Print configured model roles and adapters",
    "/reload": "Hot-reload config/*.yaml without restart",
    "/clear": "Clear the terminal screen",
    "/help": "Show list of commands and keyboard shortcuts",
    "/exit": "Stop the CLI",
    "/quit": "Alias for /exit",
}

ALIASES = {
    "reset": "new",
    "quit": "exit",
    "keys": "shortcuts",
    "providers": "provider",
    "tools": "plugins",
    "skill": "skills",
}


async def cmd_exit(_cli: Cli, _rest: str) -> str:
    return "exit"


async def cmd_help(_cli: Cli, _rest: str) -> None:
    console.print(HELP)


async def cmd_shortcuts(_cli: Cli, _rest: str) -> None:
    from ui.dialogs import show_shortcuts_dialog

    show_shortcuts_dialog()


async def cmd_clear(cli: Cli, _rest: str) -> None:
    cli.paint_shell()


async def cmd_new(cli: Cli, _rest: str) -> None:
    cli.store.save(cli.master.history, cli.mode)
    cli.store.create(cli.mode)
    cli.master.history = []
    cli.master._awaiting_clarify = False
    cli.plan_state["waiting_id"] = None
    cli.plan_state["collecting"] = ""
    try:
        cli.renderer.finish()
    except Exception:
        pass
    cli.paint_shell(notice=f"[bold]new session[/bold]  [dim]{cli.store.id}[/dim]")


async def cmd_sessions(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_sessions

    render_sessions(cli.store.list(), cli.store.id)


async def cmd_resume(cli: Cli, rest: str) -> None:
    from ui.dialogs import pick_session
    from ui.render.inventory import render_sessions

    needle = rest.strip()
    if not needle:
        rows = cli.store.list()
        if not rows:
            render_sessions(rows, cli.store.id)
            return
        needle = await pick_session(rows, cli.store.id) or ""
        if not needle:
            render_sessions(rows, cli.store.id)
            return
    cli.store.save(cli.master.history, cli.mode)
    try:
        cli.store.load(needle)
    except (KeyError, OSError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return
    cli.master.history = list(cli.store.history)
    cli.master._awaiting_clarify = False
    cli.mode = cli.store.mode or cli.mode
    cli.master.mode = cli.mode
    cli.plan_state["collecting"] = ""
    waiting = cli.plans.waiting_for(cli.store.id)
    cli.plan_state["waiting_id"] = waiting.id if waiting else None
    cli.paint_shell(
        replay=True,
        notice=(
            f"[bold]resumed[/bold] {cli.store.id}  "
            f"[dim]{cli.store.title or '(untitled)'} · {len(cli.store.history)} messages[/dim]"
        ),
    )
    if waiting:
        cli.show_plan(waiting)


async def cmd_rename(cli: Cli, rest: str) -> None:
    title = rest.strip()
    if not title:
        console.print("[yellow]Usage: /rename <title>[/yellow]")
        return
    cli.store.rename(title)
    cli.store.save(cli.master.history, cli.mode)
    console.print(f"[bold]renamed[/bold] {cli.store.title}")


async def cmd_plans(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_plans

    render_plans(cli.plans.list(), cli.plan_state["waiting_id"] or "")


async def cmd_plan(cli: Cli, rest: str) -> None:
    from ui.render.inventory import render_plan

    needle = rest.strip()
    plan = None
    if needle:
        try:
            plan = cli.plans.get(needle)
        except KeyError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            return
    else:
        plan = cli.plans.waiting_for(cli.store.id) or cli.plans.latest_for(cli.store.id)
    if plan is None:
        plan_file = cli.root / "plan.md"
        if plan_file.is_file():
            lines = plan_file.read_text(encoding="utf-8").splitlines()
            render_plan("plan.md", lines)
        else:
            render_plan("plan.md")
        return
    cli.show_plan(plan)
    if plan.status == "waiting_approval":
        cli.plan_state["waiting_id"] = plan.id


async def cmd_roles(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_roles

    render_roles(cli.stack["registry"].cfg.get("roles") or {})


async def cmd_tasks(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_tasks

    render_tasks(list(cli.stack["tasks"].tasks.values()))


async def cmd_provider(cli: Cli, _rest: str) -> None:
    from ui.dialogs import show_provider_dialog

    show_provider_dialog(cli.stack["models_cfg"])


async def cmd_mode(cli: Cli, rest: str) -> None:
    from ui.dialogs import show_mode_dialog

    if rest:
        match = next((m for m in cli.MODES if m.lower() == rest.strip().lower()), None)
        if match is None:
            console.print("[yellow]Modes: Code, Architect, Ask, Fast[/yellow]")
            return
        cli.mode = match
        cli.store.mode = cli.mode
        cli.master.mode = cli.mode
        console.print(f"[bold green]Mode {cli.mode}[/bold green]")
        return
    show_mode_dialog(cli.mode)


async def cmd_skills(cli: Cli, _rest: str) -> None:
    from ui.dialogs import show_skills_dialog

    show_skills_dialog(cli.root)


async def cmd_plugins(cli: Cli, _rest: str) -> None:
    from ui.dialogs import show_plugins_dialog

    show_plugins_dialog(cli.gate)


async def cmd_settings(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_settings

    render_settings(cli.stack["kernel_cfg"], cli.stack["perm_cfg"])


async def cmd_reload(cli: Cli, _rest: str) -> None:
    from boot import collect_secrets, load_yaml
    from brain.skills import load_skills

    cfg_dir = cli.root / "config"
    cli.stack["registry"].cfg = load_yaml(cfg_dir / "models.yaml")
    cli.stack["gate"].cfg = load_yaml(cfg_dir / "permissions.yaml")
    cli.stack["models_cfg"] = cli.stack["registry"].cfg
    cli.stack["perm_cfg"] = cli.stack["gate"].cfg
    kcfg = load_yaml(cfg_dir / "kernel.yaml")
    cli.stack["kernel_cfg"] = kcfg
    cli.master.clarify = bool(kcfg.get("clarify", True))
    cli.master.max_tool_steps = int(kcfg.get("max_tool_steps", 16))
    prompts = cli.stack["registry"].cfg.get("prompts") or {}
    cli.master.system_prompt = str(prompts.get("master") or cli.master.system_prompt)
    cli.master.clarify_prompt = str(prompts.get("clarify") or cli.master.clarify_prompt)
    cli.master.architect_prompt = str(prompts.get("architect") or cli.master.architect_prompt)
    cli.master.tools.perm_cfg = cli.stack["perm_cfg"]
    if cli.master.tools.operator is not None:
        cli.master.tools.operator.perm = cli.stack["perm_cfg"]
        if getattr(cli.master.tools.operator, "a11y", None) is not None:
            cli.master.tools.operator.a11y.perm = cli.stack["perm_cfg"]
    vpath = cfg_dir / "voice.yaml"
    if vpath.is_file():
        cli.stack["voice_cfg"] = load_yaml(vpath)
        if cli.stack.get("voice") is not None:
            cli.stack["voice"].cfg = cli.stack["voice_cfg"]
    cli.master.secrets = collect_secrets(
        cli.stack["registry"].cfg, cli.stack["perm_cfg"], cli.stack.get("voice_cfg")
    )
    mem_path = cfg_dir / "memory.yaml"
    if mem_path.is_file():
        cli.stack["memory"].cfg = load_yaml(mem_path)
        cli.stack["mem_cfg"] = cli.stack["memory"].cfg
    custom_skills_dir = kcfg.get("skills_dir")
    global_skills_dir = Path(custom_skills_dir).expanduser() if custom_skills_dir else None
    skills = load_skills(cli.root, global_dir=global_skills_dir)
    cli.master.skills = skills
    cli.stack["skills"] = skills
    console.print("[bold green]reloaded config/*.yaml and skills[/bold green]")


async def cmd_facts(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_facts

    render_facts(cli.stack["memory"].valid_facts())


async def cmd_proposals(cli: Cli, _rest: str) -> None:
    from ui.render.inventory import render_proposals

    render_proposals(cli.stack["memory"].pending())


async def cmd_consolidate(cli: Cli, _rest: str) -> None:
    from brain.librarian import draft

    console.print("[dim]Librarian consolidation…[/dim]")
    result = await draft(cli.stack["memory"], cli.stack["registry"], cli.bus)
    console.print(f"[bold green]{result}[/bold green]")


async def cmd_approve(cli: Cli, rest: str) -> None:
    if rest.strip() in ("all",):
        applied = cli.stack["memory"].approve_all()
        console.print(f"[bold green]approved {len(applied)} proposals[/bold green]")
        return
    ids = rest.split()
    if not ids:
        console.print("[yellow]Usage: /approve <id> [id...]  or  /approve all[/yellow]")
        return
    for cid in ids:
        if cli.gate.resolve(cid, True):
            console.print(f"[bold green]approved card {cid}[/bold green]")
        elif cli.stack["memory"].approve([cid]):
            console.print(f"[bold green]approved proposal {cid}[/bold green]")
        else:
            console.print(f"[bold red]No such card/proposal ID: {cid}[/bold red]")


async def cmd_deny(cli: Cli, rest: str) -> None:
    ids = rest.split()
    if not ids:
        console.print("[yellow]Usage: /deny <id> [id...][/yellow]")
        return
    for cid in ids:
        if cli.gate.resolve(cid, False):
            console.print(f"[bold yellow]denied card {cid}[/bold yellow]")
        elif cli.stack["memory"].reject([cid]):
            console.print(f"[bold yellow]rejected proposal {cid}[/bold yellow]")
        else:
            console.print(f"[bold red]No such card/proposal ID: {cid}[/bold red]")


async def cmd_steer(cli: Cli, rest: str) -> None:
    parts = rest.split(None, 1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /steer <id> <text>[/yellow]")
        return
    try:
        await cli.tasks.steer(parts[0], parts[1])
        console.print(f"[bold green]steered {parts[0]}[/bold green]")
    except (KeyError, ValueError) as exc:
        console.print(f"[bold red]{exc}[/bold red]")


async def cmd_orb(cli: Cli, _rest: str) -> None:
    o = cli.stack.get("orb")
    if o is None:
        console.print("[yellow]orb is off[/yellow]  python main.py --cli --voice")
        return
    o.toggle_visible()


async def cmd_listen(cli: Cli, rest: str) -> None:
    import asyncio

    voice = cli.stack.get("voice")
    if voice is None:
        console.print("[yellow]voice is off[/yellow]  python main.py --cli --voice")
        return
    try:
        if voice.origin and not voice.waiting_for_card:
            console.print("[yellow]voice turn in progress[/yellow]")
            return
        if rest:
            item: str | bytes = rest
        else:
            if voice.recording:
                voice.stop_record()
                console.print("[dim]stopped listening[/dim]")
                return
            console.print("[dim][listening] speak, then Enter[/dim]")
            halt = asyncio.Event()
            rec = asyncio.create_task(voice.record(halt, use_vad=False))
            try:
                await cli.read_line()
            except (EOFError, KeyboardInterrupt):
                halt.set()
                rec.cancel()
                return
            halt.set()
            item = await rec
        if voice.waiting_for_card:
            heard = item if isinstance(item, str) else await voice.transcribe(item)
            if heard:
                await voice.hear(heard)
            return
        text = item if isinstance(item, str) else await voice.transcribe(item)
        await voice.utter(text=text, turn=cli.voice_turn)
    except Exception as exc:
        console.print(f"[bold red]voice[/bold red] {exc}")


async def cmd_task(cli: Cli, rest: str) -> None:
    title, _, prompt = rest.partition(" ")
    if not prompt:
        console.print("[yellow]Usage: /task <title> <prompt>[/yellow]")
        return

    async def factory(task, prompt=prompt):
        await cli.master.turn(prompt, task=task)

    t = cli.tasks.spawn(title, factory)
    console.print(f"[bold green]task {t.id} queued[/bold green] {title}")


COMMANDS: dict[str, Handler] = {
    "exit": cmd_exit,
    "help": cmd_help,
    "shortcuts": cmd_shortcuts,
    "clear": cmd_clear,
    "new": cmd_new,
    "sessions": cmd_sessions,
    "resume": cmd_resume,
    "rename": cmd_rename,
    "plans": cmd_plans,
    "plan": cmd_plan,
    "roles": cmd_roles,
    "tasks": cmd_tasks,
    "provider": cmd_provider,
    "mode": cmd_mode,
    "skills": cmd_skills,
    "plugins": cmd_plugins,
    "settings": cmd_settings,
    "reload": cmd_reload,
    "facts": cmd_facts,
    "proposals": cmd_proposals,
    "consolidate": cmd_consolidate,
    "approve": cmd_approve,
    "deny": cmd_deny,
    "steer": cmd_steer,
    "orb": cmd_orb,
    "listen": cmd_listen,
    "task": cmd_task,
}

BUILTIN_COMMANDS = set(COMMANDS) | set(ALIASES) | {"approve-all"}


async def _run_skill(cli: Cli, sname: str, rest: str) -> None:
    from brain.skills import find_skill, format_skill_turn

    skill = find_skill(sname, cli.stack.get("skills") or [])
    if skill is None:
        console.print(f"[yellow]unknown skill /{sname}[/yellow]")
        return
    shown = f"/{skill.name}" + (f" {rest}" if rest else "")
    request = cli.attach_files(rest) if rest else rest
    await cli.run_foreground(
        format_skill_turn(skill, request),
        shown=shown,
        skip_clarify=True,
    )


async def handle_line(cli: Cli, line: str) -> str | None:
    from ui.completer import resolve_slash
    from ui.plans import execute_prompt, plan_action, revise_prompt

    line = line.strip()
    if not line:
        return None
    if line.startswith("/"):
        kind, sname, rest = resolve_slash(line, cli.stack.get("skills") or [])
        if kind == "unknown":
            console.print(
                f"[yellow]unknown command /{sname}[/yellow]  [dim]/help  /shortcuts  /skills[/dim]"
            )
            return None
        if kind == "skill":
            await _run_skill(cli, sname, rest)
            return None
        if sname == "approve-all":
            sname, rest = "approve", "all"
        sname = ALIASES.get(sname, sname)
        fn = COMMANDS.get(sname)
        if fn is None:
            console.print(
                f"[yellow]unknown command /{sname}[/yellow]  [dim]/help  /shortcuts  /skills[/dim]"
            )
            return None
        return await fn(cli, rest)

    kind, payload = plan_action(
        line,
        waiting=bool(cli.plan_state["waiting_id"]),
        collecting=cli.plan_state["collecting"],
    )
    if kind == "approve":
        pid = cli.plan_state["waiting_id"]
        cli.plan_state["waiting_id"] = None
        cli.plan_state["collecting"] = ""
        plan = cli.plans.set_status(pid, "approved")
        cli.mode = "Code"
        cli.store.mode = cli.mode
        cli.master.mode = cli.mode
        cli.show_plan(plan)
        await cli.run_foreground(
            execute_prompt(plan),
            shown="(approved plan)",
            skip_clarify=True,
        )
        return None
    if kind == "quit":
        pid = cli.plan_state["waiting_id"]
        cli.plan_state["waiting_id"] = None
        cli.plan_state["collecting"] = ""
        plan = cli.plans.set_status(pid, "discarded")
        cli.show_plan(plan)
        return None
    if kind == "ask_changes":
        cli.plan_state["collecting"] = "changes"
        console.print("[dim]describe the changes[/dim]")
        return None
    if kind == "ask_comment":
        cli.plan_state["collecting"] = "comment"
        console.print("[dim]comment on the plan[/dim]")
        return None
    if kind in ("changes", "comment"):
        pid = cli.plan_state["waiting_id"]
        cli.plan_state["collecting"] = ""
        cli.plans.set_status(pid, "changes_requested", comment=f"{kind}: {payload}")
        cli.mode = "Architect"
        cli.store.mode = cli.mode
        cli.master.mode = cli.mode
        await cli.run_foreground(
            revise_prompt(payload, kind),
            shown=payload,
            skip_clarify=True,
        )
        return None

    await cli.run_foreground(cli.attach_files(line), shown=line)
    return None
