"""Boot the kernel. `python main.py --cli` is the Phase 1 surface."""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


import yaml
from dotenv import load_dotenv

from brain.master import Master
from brain.registry import Registry
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tools import NativeTools
from tools.operator import Operator

ROOT = Path(__file__).resolve().parent


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def collect_secrets(models_cfg: dict) -> list[str]:
    found = []
    for pcfg in (models_cfg.get("providers") or {}).values():
        env = pcfg.get("api_key_env")
        if env and os.environ.get(env):
            found.append(os.environ[env])
    return found


def boot(root: Path):
    load_dotenv(root / ".env")
    cfg_dir = root / "config"
    models_cfg = load_yaml(cfg_dir / "models.yaml")
    perm_cfg = load_yaml(cfg_dir / "permissions.yaml")
    kernel_cfg = load_yaml(cfg_dir / "kernel.yaml")
    mem_path = cfg_dir / "memory.yaml"
    mem_cfg = load_yaml(mem_path) if mem_path.is_file() else {}
    bus = Bus()
    slots = int(kernel_cfg.get("concurrent_slots", 4))
    gate = Gate(perm_cfg, bus)
    tasks = TaskManager(bus, concurrent_slots=slots)
    registry = Registry(models_cfg)
    data_dir = root / str(kernel_cfg.get("data_dir", "data"))
    memory = Episodic(data_dir / "events.db", cfg=mem_cfg, bus=bus)
    tools = NativeTools(
        root,
        perm_cfg,
        max_chars=int(kernel_cfg.get("tool_result_max_chars", 8000)),
    )
    tools.operator = Operator(
        perm_cfg,
        bus,
        memory,
        root,
        registry=registry,
        tools=tools,
    )
    prompts = models_cfg.get("prompts") or {}
    custom_skills_dir = kernel_cfg.get("skills_dir")
    global_skills_dir = Path(custom_skills_dir).expanduser() if custom_skills_dir else None
    from brain.skills import load_skills
    skills = load_skills(root, global_dir=global_skills_dir)

    master = Master(
        registry,
        gate,
        tasks,
        memory,
        tools,
        bus,
        system_prompt=str(prompts.get("master") or "You are Friday."),
        clarify_prompt=str(prompts.get("clarify") or ""),
        clarify=bool(kernel_cfg.get("clarify", True)),
        max_tool_steps=int(kernel_cfg.get("max_tool_steps", 16)),
        secrets=collect_secrets(models_cfg),
        skills=skills,
    )
    return {
        "root": root,
        "bus": bus,
        "gate": gate,
        "tasks": tasks,
        "registry": registry,
        "memory": memory,
        "master": master,
        "models_cfg": models_cfg,
        "perm_cfg": perm_cfg,
        "kernel_cfg": kernel_cfg,
        "mem_cfg": mem_cfg,
        "skills": skills,
    }


HELP = """\
[bold #e0af68]◆ Friday Commands & Shortcuts[/bold #e0af68]
  [bold white]/new[/bold white]                   Fresh conversation (saves the current one)
  [bold white]/resume [id][/bold white]           Pick a session, or load one by id
  [bold white]/sessions[/bold white]              List saved conversations
  [bold white]/rename <title>[/bold white]        Name the current session
  [bold white]/shortcuts[/bold white]             Full keyboard shortcuts & command palette (Ctrl+X)
  [bold white]/plan[/bold white]                  Inspect active plan review block
  [bold white]@path[/bold white]                  Attach a workspace file (Tab completes)
  [bold white]/help[/bold white]                  This cheatsheet
  [bold white]/mode [name][/bold white]           Code, Architect, Ask, Fast
  [bold white]/provider[/bold white]              Configured LLM providers
  [bold white]/skills[/bold white]                Active skills
  [bold white]/skill <name> [args][/bold white]   Run a skill (also /<name>)
  [bold white]/plugins[/bold white]               Tools & ring specifications
  [bold white]/settings[/bold white]              Runtime dials (clarify, slots, etc.)
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


def _create_prompt_session(
    stack_getter, get_toolbar, get_title, history_path: Path, on_cycle_mode=None
):
    """Framed composer, or a two-line PromptSession if the box cannot start."""
    from ui.composer import create_composer

    box = create_composer(
        stack_getter, get_toolbar, get_title, history_path, on_cycle_mode=on_cycle_mode
    )
    if box is not None:
        return box
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style
        from ui.completer import FridayCommandCompleter

        style = Style.from_dict({
            "bottom-toolbar": "#e1e1e1 bg:#161618",
            "bottom-toolbar.text": "#e1e1e1",
            "placeholder": "#6c6c6c italic",
        })
        history_path.parent.mkdir(parents=True, exist_ok=True)
        return PromptSession(
            completer=FridayCommandCompleter(stack_getter),
            bottom_toolbar=get_toolbar,
            style=style,
            history=FileHistory(str(history_path)),
            complete_while_typing=True,
            reserve_space_for_menu=8,
            erase_when_done=True,
        )
    except Exception:
        return None


def _friday_prompt(store, mode: str, cwd: str = "", branch: str = ""):
    from prompt_toolkit.formatted_text import HTML

    title = html.escape((store.title or "new session")[:40])
    sid = html.escape(store.id)
    mode_s = html.escape(mode)
    cwd_s = html.escape(cwd)
    branch_bit = (
        f' <style fg="#00ff00">{html.escape(branch)}</style>' if branch else ""
    )
    cwd_bit = f" <b>{cwd_s}</b>" if cwd_s else " <b>Friday</b>"
    return HTML(
        f'<style fg="#505050">╭─</style>{cwd_bit}'
        f"{branch_bit}"
        f' <style fg="#8b8b90">{sid}</style>'
        f' <style fg="#e0af68">{mode_s}</style>'
        f' <style fg="#8b8b90">{title}</style>\n'
        f'<style fg="#505050">│</style> '
    )


async def run_cli(root: Path) -> None:
    try:
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.patch_stdout import patch_stdout
    except ImportError:
        HTML = None
        patch_stdout = None

    from ui import (
        SessionStore,
        TurnRenderer,
        console,
        display_cwd,
        git_branch,
        pick_session,
        render_banner,
        render_card,
        render_facts,
        render_history,
        render_plan,
        render_proposals,
        render_roles,
        render_sessions,
        render_settings,
        render_shortcuts,
        render_tasks,
        render_user,
        resolve_slash,
        show_mode_dialog,
        show_plugins_dialog,
        show_provider_dialog,
        show_shortcuts_dialog,
        show_skills_dialog,
    )
    import ui.renderer as ui_renderer

    stack = boot(root)
    bus: Bus = stack["bus"]
    gate: Gate = stack["gate"]
    tasks: TaskManager = stack["tasks"]
    master: Master = stack["master"]
    data_dir = root / str(stack["kernel_cfg"].get("data_dir", "data"))
    store = SessionStore(data_dir / "sessions")
    stack["sessions"] = store
    renderer = TurnRenderer(console)
    current_mode = "Code"
    ui_state = {"foreground": False}

    async def watch(topic: str, handler) -> None:
        q = bus.subscribe(topic)
        while True:
            result = handler(await q.get())
            if asyncio.iscoroutine(result):
                await result

    def on_state(ev: dict) -> None:
        if ev.get("task_id") and ui_state["foreground"]:
            return
        phase = ev.get("phase")
        if phase == "thinking":
            renderer.on_thinking()
        elif phase == "token":
            renderer.on_token(ev.get("text") or "")
        elif phase == "stuck":
            renderer.on_stuck(ev.get("question") or "")
        elif phase == "idle":
            renderer.on_idle()
            store.save(master.history, current_mode)

    def on_tool_call(ev: dict) -> None:
        if ev.get("task_id") and ui_state["foreground"]:
            return
        renderer.on_tool_call(ev.get("name") or "", ev.get("args") or {}, int(ev.get("ring") or 1))

    def on_tool_result(ev: dict) -> None:
        if ev.get("task_id") and ui_state["foreground"]:
            return
        renderer.on_tool_result(ev.get("name") or "", ev.get("result") or "")

    async def on_card(ev: dict) -> None:
        renderer.on_card()
        render_card(ev)
        cid = ev.get("id", "")
        if not ui_state["foreground"] or cid not in gate.pending():
            return
        try:
            from prompt_toolkit import PromptSession

            choice = await PromptSession().prompt_async(
                HTML('<style fg="#f38ba8">  allow?</style> <style fg="#6c7086">[y/n]</style> ')
                if HTML
                else "  allow? [y/n] "
            )
        except (EOFError, KeyboardInterrupt, Exception):
            choice = "n"
        if cid in gate.pending():
            ok = str(choice).strip().lower() in ("y", "yes", "a", "allow")
            gate.resolve(cid, ok)
            console.print("[green]allowed[/green]" if ok else "[yellow]denied[/yellow]")

    def on_resolved(ev: dict) -> None:
        if not ev.get("expired"):
            return
        cid = ev.get("id", "")
        fate = "allowed" if ev.get("approved") else "denied"
        console.print(f"[yellow]card {cid} expired → {fate}[/yellow]")

    def on_error(ev: dict) -> None:
        console.print(f"\n[bold red]error[/bold red] {ev.get('error')}")

    watchers = [
        asyncio.create_task(watch("agent.state", on_state)),
        asyncio.create_task(watch("tool.call", on_tool_call)),
        asyncio.create_task(watch("tool.result", on_tool_result)),
        asyncio.create_task(watch("approval.request", on_card)),
        asyncio.create_task(watch("approval.resolved", on_resolved)),
        asyncio.create_task(watch("error", on_error)),
    ]

    master_model = stack["models_cfg"].get("roles", {}).get("master", "claude-3-7-sonnet")

    def workspace_bits() -> tuple[str, str]:
        return display_cwd(root), git_branch(root)

    def paint_shell(*, replay: bool = False, notice: str = "") -> None:
        cwd_s, branch_s = workspace_bits()
        console.clear()
        render_banner(
            model=master_model,
            mode=current_mode,
            cwd=cwd_s,
            branch=branch_s,
            session_id=store.id,
            title=store.title,
        )
        if notice:
            console.print(notice)
        if replay:
            render_history(master.history)

    cwd_s, branch_s = workspace_bits()
    render_banner(
        model=master_model,
        mode=current_mode,
        cwd=cwd_s,
        branch=branch_s,
        session_id=store.id,
        title=store.title,
    )

    def get_bottom_toolbar():
        if HTML is None:
            return None
        try:
            cols = shutil.get_terminal_size(fallback=(100, 24)).columns
            m_model = html.escape(str(stack["models_cfg"].get("roles", {}).get("master", "default")))
            short_model = m_model.split("/")[-1] if "/" in m_model else m_model
            mem = stack.get("memory")
            facts_cnt = len(mem.valid_facts()) if mem else 0
            prop_cnt = len(mem.pending()) if mem else 0
            cards = len(gate.pending())
            tsks = stack.get("tasks")
            running_cnt = len([t for t in tsks.tasks.values() if t.status == "running"]) if tsks else 0
            cwd_s, branch_s = workspace_bits()
            short_cwd = cwd_s.split("/")[-1] if "/" in cwd_s else (cwd_s.split("\\")[-1] if "\\" in cwd_s else cwd_s)
            card_bit = (
                f" <style fg='#f38ba8'><b>● {cards} cards</b></style> │"
                if cards
                else ""
            )
            task_bit = (
                f" <style fg='#00ff00'>● {running_cnt} tasks</style> │"
                if running_cnt
                else f" ⚙ {running_cnt} tasks │"
            )
            branch_bit = (
                f" <style fg='#00ff00'>git:{html.escape(branch_s)}</style> │"
                if branch_s
                else ""
            )

            if cols >= 110:
                return HTML(
                    f" {html.escape(cwd_s)} │"
                    f"{branch_bit}"
                    f" <style fg='#8b8b90'>{m_model}</style> │"
                    f" <style fg='#e0af68'>{html.escape(current_mode)}</style> │"
                    f" <style fg='#8b8b90'>{html.escape(store.id)}</style> │"
                    f"{card_bit}"
                    f" {facts_cnt} facts │"
                    f" {prop_cnt} proposals │"
                    f"{task_bit}"
                    f" <style fg='#e0af68'>Ctrl+X</style> shortcuts "
                )
            elif cols >= 75:
                return HTML(
                    f" {html.escape(short_cwd)} │"
                    f"{branch_bit}"
                    f" <style fg='#8b8b90'>{short_model}</style> │"
                    f" <style fg='#e0af68'>{html.escape(current_mode)}</style> │"
                    f"{card_bit}"
                    f"{task_bit}"
                    f" <style fg='#e0af68'>Ctrl+X</style> "
                )
            else:
                return HTML(
                    f" <style fg='#e0af68'>{html.escape(current_mode)}</style> │"
                    f"{card_bit}"
                    f" <style fg='#e0af68'>Ctrl+X</style> "
                )
        except Exception:
            return HTML(" <b>Friday</b> │ /shortcuts ") if HTML else None

    def get_composer_title():
        if HTML is None:
            return f"{store.id} {current_mode}"
        cwd_s, branch_s = workspace_bits()
        cols = shutil.get_terminal_size(fallback=(100, 24)).columns
        bits = []
        if cols >= 90:
            bits.append(f"<b>{html.escape(cwd_s)}</b>")
            if branch_s:
                bits.append(f'<style fg="#00ff00">git:{html.escape(branch_s)}</style>')
            bits.append(f'<style fg="#8b8b90">{html.escape(store.id)}</style>')
            bits.append(f'<style fg="#e0af68">{html.escape(current_mode)}</style>')
            title = html.escape((store.title or "new session")[:24])
            bits.append(f'<style fg="#8b8b90">{title}</style>')
        elif cols >= 60:
            short_cwd = cwd_s.split("/")[-1] if "/" in cwd_s else (cwd_s.split("\\")[-1] if "\\" in cwd_s else cwd_s)
            bits.append(f"<b>{html.escape(short_cwd)}</b>")
            if branch_s:
                bits.append(f'<style fg="#00ff00">git:{html.escape(branch_s)}</style>')
            bits.append(f'<style fg="#8b8b90">{html.escape(store.id)}</style>')
            bits.append(f'<style fg="#e0af68">{html.escape(current_mode)}</style>')
        else:
            bits.append(f'<style fg="#e0af68">{html.escape(current_mode)}</style>')
            bits.append(f'<style fg="#8b8b90">{html.escape(store.id)}</style>')
        return HTML(" · ".join(bits))

    MODES = ("Code", "Architect", "Ask", "Fast")

    def cycle_mode() -> None:
        nonlocal current_mode
        i = next((n for n, m in enumerate(MODES) if m.lower() == current_mode.lower()), 0)
        current_mode = MODES[(i + 1) % len(MODES)]
        store.mode = current_mode

    session = _create_prompt_session(
        lambda: stack,
        get_bottom_toolbar,
        get_composer_title,
        data_dir / ".cli_history",
        on_cycle_mode=cycle_mode,
    )

    async def read_line() -> str:
        if session:
            from ui.composer import Composer

            if isinstance(session, Composer):
                return await session.prompt_async()
            cwd_s, branch_s = workspace_bits()
            return await session.prompt_async(
                lambda: _friday_prompt(store, current_mode, cwd_s, branch_s),
                placeholder=HTML('<style color="#6c6c6c">message, @file, or /command</style>') if HTML else None,
            )
        return await asyncio.to_thread(input, "Friday> ")

    def attach_files(text: str) -> str:
        from ui.mentions import expand_mentions

        max_chars = int(stack["kernel_cfg"].get("tool_result_max_chars", 8000))
        return expand_mentions(text, root, max_chars=max_chars)

    async def run_foreground(prompt: str, *, shown: str, skip_clarify: bool = False) -> None:
        render_user(shown)
        if not session:
            asyncio.create_task(master.turn(prompt, skip_clarify=skip_clarify))
            return
        renderer.begin_turn()
        ui_state["foreground"] = True
        try:
            await master.turn(prompt, skip_clarify=skip_clarify)
        except (KeyboardInterrupt, asyncio.CancelledError):
            console.print("[yellow]turn cancelled[/yellow]")
        except Exception as exc:
            console.print(f"[bold red]error[/bold red] {exc}")

        finally:
            ui_state["foreground"] = False
            renderer.finish()
            store.save(master.history, current_mode)

    stdout_patch = None
    try:
        if patch_stdout:
            stdout_patch = patch_stdout(raw=True)
            stdout_patch.__enter__()
        while True:
            try:
                line = await read_line()
            except (EOFError, KeyboardInterrupt):
                break

            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):
                kind, sname, rest = resolve_slash(line, stack.get("skills") or [])
                if kind == "unknown":
                    console.print(
                        f"[yellow]unknown command /{sname}[/yellow]  [dim]/help  /shortcuts  /skills[/dim]"
                    )
                    continue
                if kind == "skill":
                    from brain.skills import find_skill, format_skill_turn

                    skill = find_skill(sname, stack.get("skills") or [])
                    if skill is None:
                        console.print(f"[yellow]unknown skill /{sname}[/yellow]")
                        continue
                    shown = f"/{skill.name}" + (f" {rest}" if rest else "")
                    request = attach_files(rest) if rest else rest
                    await run_foreground(
                        format_skill_turn(skill, request),
                        shown=shown,
                        skip_clarify=True,
                    )
                    continue

            if line in ("/quit", "/exit"):
                break
            if line in ("/shortcuts", "/keys"):
                show_shortcuts_dialog()
                continue
            if line == "/plan":
                plan_file = root / "plan.md"
                if plan_file.is_file():
                    lines = plan_file.read_text(encoding="utf-8").splitlines()
                    render_plan("plan.md", lines)
                else:
                    render_plan("plan.md")
                continue
            if line == "/help":
                console.print(HELP)
                continue

            if line == "/clear":
                paint_shell()
                continue
            if line in ("/new", "/reset"):
                store.save(master.history, current_mode)
                store.create(current_mode)
                master.history = []
                master._awaiting_clarify = False
                paint_shell(notice=f"[bold]new session[/bold]  [dim]{store.id}[/dim]")
                continue
            if line == "/sessions":
                render_sessions(store.list(), store.id)
                continue
            if line == "/resume" or line.startswith("/resume "):
                needle = line.split(None, 1)[1].strip() if " " in line else ""
                if not needle:
                    rows = store.list()
                    if not rows:
                        render_sessions(rows, store.id)
                        continue
                    needle = await pick_session(rows, store.id) or ""
                    if not needle:
                        render_sessions(rows, store.id)
                        continue
                store.save(master.history, current_mode)
                try:
                    store.load(needle)
                except (KeyError, OSError, ValueError) as exc:
                    console.print(f"[bold red]{exc}[/bold red]")
                    continue
                master.history = list(store.history)
                master._awaiting_clarify = False
                current_mode = store.mode or current_mode
                paint_shell(
                    replay=True,
                    notice=(
                        f"[bold]resumed[/bold] {store.id}  "
                        f"[dim]{store.title or '(untitled)'} · {len(store.history)} messages[/dim]"
                    ),
                )
                continue
            if line.startswith("/rename"):
                title = line.split(None, 1)[1].strip() if " " in line else ""
                if not title:
                    console.print("[yellow]Usage: /rename <title>[/yellow]")
                    continue
                store.rename(title)
                store.save(master.history, current_mode)
                console.print(f"[bold]renamed[/bold] {store.title}")
                continue
            if line == "/roles":
                render_roles(stack["registry"].cfg.get("roles") or {})
                continue
            if line == "/tasks":
                render_tasks(list(stack["tasks"].tasks.values()))
                continue
            if line == "/provider" or line == "/providers":
                show_provider_dialog(stack["models_cfg"])
                continue
            if line.startswith("/mode"):
                parts = line.split(None, 1)
                if len(parts) == 2:
                    match = next((m for m in MODES if m.lower() == parts[1].strip().lower()), None)
                    if match is None:
                        console.print("[yellow]Modes: Code, Architect, Ask, Fast[/yellow]")
                        continue
                    current_mode = match
                    store.mode = current_mode
                    console.print(f"[bold green]Mode {current_mode}[/bold green]")
                else:
                    show_mode_dialog(current_mode)
                continue
            if line in ("/skills", "/skill"):
                show_skills_dialog(root)
                continue
            if line == "/plugins" or line == "/tools":
                show_plugins_dialog(gate)
                continue
            if line == "/settings":
                render_settings(stack["kernel_cfg"], stack["perm_cfg"])
                continue
            if line == "/reload":
                cfg_dir = root / "config"
                stack["registry"].cfg = load_yaml(cfg_dir / "models.yaml")
                stack["gate"].cfg = load_yaml(cfg_dir / "permissions.yaml")
                stack["models_cfg"] = stack["registry"].cfg
                stack["perm_cfg"] = stack["gate"].cfg
                kcfg = load_yaml(cfg_dir / "kernel.yaml")
                stack["kernel_cfg"] = kcfg
                master.clarify = bool(kcfg.get("clarify", True))
                master.max_tool_steps = int(kcfg.get("max_tool_steps", 16))
                prompts = stack["registry"].cfg.get("prompts") or {}
                master.system_prompt = str(prompts.get("master") or master.system_prompt)
                master.clarify_prompt = str(prompts.get("clarify") or master.clarify_prompt)
                master.secrets = collect_secrets(stack["registry"].cfg)
                mem_path = cfg_dir / "memory.yaml"
                if mem_path.is_file():
                    stack["memory"].cfg = load_yaml(mem_path)
                    stack["mem_cfg"] = stack["memory"].cfg
                from brain.skills import load_skills
                custom_skills_dir = kcfg.get("skills_dir")
                global_skills_dir = Path(custom_skills_dir).expanduser() if custom_skills_dir else None
                skills = load_skills(root, global_dir=global_skills_dir)
                master.skills = skills
                stack["skills"] = skills
                console.print("[bold green]reloaded config/*.yaml and skills[/bold green]")
                continue
            if line == "/facts":
                render_facts(stack["memory"].valid_facts())
                continue
            if line == "/proposals":
                render_proposals(stack["memory"].pending())
                continue
            if line == "/consolidate":
                from brain.librarian import draft

                console.print("[dim]Librarian consolidation…[/dim]")
                result = await draft(stack["memory"], stack["registry"], bus)
                console.print(f"[bold green]{result}[/bold green]")
                continue
            if line == "/approve all" or line == "/approve-all":
                applied = stack["memory"].approve_all()
                console.print(f"[bold green]approved {len(applied)} proposals[/bold green]")
                continue
            if line.startswith("/approve "):
                ids = line.split(None, 1)[1].split()
                for cid in ids:
                    if gate.resolve(cid, True):
                        console.print(f"[bold green]approved card {cid}[/bold green]")
                    elif stack["memory"].approve([cid]):
                        console.print(f"[bold green]approved proposal {cid}[/bold green]")
                    else:
                        console.print(f"[bold red]No such card/proposal ID: {cid}[/bold red]")
                continue
            if line.startswith("/deny "):
                ids = line.split(None, 1)[1].split()
                for cid in ids:
                    if gate.resolve(cid, False):
                        console.print(f"[bold yellow]denied card {cid}[/bold yellow]")
                    elif stack["memory"].reject([cid]):
                        console.print(f"[bold yellow]rejected proposal {cid}[/bold yellow]")
                    else:
                        console.print(f"[bold red]No such card/proposal ID: {cid}[/bold red]")
                continue
            if line.startswith("/steer "):
                parts = line.split(None, 2)
                if len(parts) < 3:
                    console.print("[yellow]Usage: /steer <id> <text>[/yellow]")
                    continue
                try:
                    await tasks.steer(parts[1], parts[2])
                    console.print(f"[bold green]steered {parts[1]}[/bold green]")
                except (KeyError, ValueError) as exc:
                    console.print(f"[bold red]{exc}[/bold red]")
                continue
            if line.startswith("/task "):
                rest = line[6:].strip()
                title, _, prompt = rest.partition(" ")
                if not prompt:
                    console.print("[yellow]Usage: /task <title> <prompt>[/yellow]")
                    continue

                async def factory(task, prompt=prompt):
                    await master.turn(prompt, task=task)

                t = tasks.spawn(title, factory)
                console.print(f"[bold green]task {t.id} queued[/bold green] {title}")
                continue

            await run_foreground(attach_files(line), shown=line)
    finally:
        if stdout_patch is not None:
            try:
                stdout_patch.__exit__(None, None, None)
            except Exception:
                pass
        for w in watchers:
            w.cancel()
        store.save(master.history, current_mode)
        stack["memory"].close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS")
    parser.add_argument("--cli", action="store_true", help="interactive chat loop")
    parser.add_argument("--eval", action="store_true", help="run the Phase 2 eval suite")
    parser.add_argument("--root", default=str(ROOT), help="repo root (configs live in <root>/config)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.eval:
        import json

        from evals.harness import run_suite

        path = asyncio.run(run_suite(root))
        summary = json.loads(path.read_text(encoding="utf-8"))
        print(path)
        print(
            f"success_pct={summary['success_pct']} latency_ms={summary['latency_ms']} "
            f"token_cost={summary['token_cost']} human_interventions={summary['human_interventions']} "
            f"cost_per_accepted_outcome={summary['cost_per_accepted_outcome']}"
        )
        return
    if args.cli:
        asyncio.run(run_cli(root))
        return
    parser.print_help()
    print("\nPhase 1 surface is the CLI: python main.py --cli")
    print("Phase 2 eval suite: python main.py --eval")


if __name__ == "__main__":
    main()
