"""Interactive CLI loop. `python main.py --cli` is the Phase 1 surface."""

from __future__ import annotations

import asyncio
import html
import shutil
import sys
from pathlib import Path

from boot import boot
from kernel import Bus, Gate, TaskManager
from brain.master import Master
from ui.commands import handle_line
from ui.render.theme import coerce_ring, console
from ui.sessions import SessionStore


def _create_prompt_session(
    stack_getter, get_toolbar, get_title, history_path: Path, on_cycle_mode=None, get_input_mode=None
):
    """Framed composer, or a two-line PromptSession if the box cannot start."""
    from ui.composer import create_composer

    box = create_composer(
        stack_getter,
        get_toolbar,
        get_title,
        history_path,
        on_cycle_mode=on_cycle_mode,
        get_input_mode=get_input_mode,
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


class Cli:
    MODES = ("Code", "Architect", "Ask", "Fast")

    def __init__(self, root: Path, *, voice_flag: bool = False) -> None:
        self.root = root
        self.voice_flag = voice_flag
        self.stack = boot(root)
        self.bus: Bus = self.stack["bus"]
        self.gate: Gate = self.stack["gate"]
        self.tasks: TaskManager = self.stack["tasks"]
        self.master: Master = self.stack["master"]
        data_dir = root / str(self.stack["kernel_cfg"].get("data_dir", "data"))
        self.store = SessionStore(data_dir / "sessions")
        self.stack["sessions"] = self.store
        from ui.plans import PlanStore

        self.plans = PlanStore(data_dir / "plans")
        self.stack["plans"] = self.plans
        from ui.render.turn import TurnRenderer

        self.renderer = TurnRenderer(console)
        self.mode = "Code"
        self.ui_state = {"foreground": False, "prompt_up": False}
        self.plan_state = {"waiting_id": None, "collecting": ""}
        self.session = None
        self.HTML = None
        self.turn_lock = asyncio.Lock()
        self.watchers: list[asyncio.Task] = []
        self.master_model = self.stack["models_cfg"].get("roles", {}).get("master", "claude-3-7-sonnet")
        self._history_path = data_dir / ".cli_history"

    def input_mode(self) -> str:
        if self.plan_state["collecting"]:
            return "plan_feedback"
        if self.plan_state["waiting_id"]:
            return "plan_approval"
        return "normal"

    def mode_label(self) -> str:
        im = self.input_mode()
        if im == "plan_approval":
            return "plan approval"
        if im == "plan_feedback":
            return "plan feedback"
        return self.mode

    def workspace_bits(self) -> tuple[str, str]:
        from ui.workspace import display_cwd, git_branch

        return display_cwd(self.root), git_branch(self.root)

    def paint_shell(self, *, replay: bool = False, notice: str = "") -> None:
        from ui.render.banner import render_banner
        from ui.render.inventory import render_history
        from ui.render.theme import clear_screen

        cwd_s, branch_s = self.workspace_bits()
        clear_screen(console)
        render_banner(
            model=self.master_model,
            mode=self.mode,
            cwd=cwd_s,
            branch=branch_s,
            session_id=self.store.id,
            title=self.store.title,
        )
        if notice:
            console.print(notice)
        if replay:
            render_history(self.master.history)

    def show_plan(self, plan) -> None:
        from ui.render.inventory import render_plan

        render_plan("plan.md", (plan.body or "").splitlines() or [""], status=plan.status)

    def present_written_plan(self, before: str | None) -> None:
        from ui.plans import updated_plan_body

        body = updated_plan_body(self.mode, self.root / "plan.md", before)
        if body is None:
            return
        plan = self.plans.upsert_waiting(self.store.id, body)
        self.plan_state["waiting_id"] = plan.id
        self.show_plan(plan)

    def attach_files(self, text: str) -> str:
        from ui.mentions import expand_mentions

        max_chars = int(self.stack["kernel_cfg"].get("tool_result_max_chars", 8000))
        return expand_mentions(text, self.root, max_chars=max_chars)

    def cycle_mode(self) -> None:
        i = next((n for n, m in enumerate(self.MODES) if m.lower() == self.mode.lower()), 0)
        self.mode = self.MODES[(i + 1) % len(self.MODES)]
        self.store.mode = self.mode
        self.master.mode = self.mode

    def get_bottom_toolbar(self):
        if self.HTML is None:
            return None
        try:
            cols = shutil.get_terminal_size(fallback=(100, 24)).columns
            m_model = html.escape(str(self.stack["models_cfg"].get("roles", {}).get("master", "default")))
            short_model = m_model.split("/")[-1] if "/" in m_model else m_model
            mem = self.stack.get("memory")
            facts_cnt = len(mem.valid_facts()) if mem else 0
            prop_cnt = len(mem.pending()) if mem else 0
            cards = len(self.gate.pending())
            tsks = self.stack.get("tasks")
            running_cnt = len([t for t in tsks.tasks.values() if t.status == "running"]) if tsks else 0
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

            # Toolbar shows state (model/session/counts). Location + mode live
            # in the Frame title above, so they are not repeated here.
            if cols >= 110:
                return self.HTML(
                    f" <style fg='#8b8b90'>{m_model}</style> │"
                    f" <style fg='#8b8b90'>{html.escape(self.store.id)}</style> │"
                    f"{card_bit}"
                    f" {facts_cnt} facts │"
                    f" {prop_cnt} proposals │"
                    f"{task_bit}"
                    f" <style fg='#e0af68'>Ctrl+X</style> shortcuts "
                )
            if cols >= 75:
                return self.HTML(
                    f" <style fg='#8b8b90'>{short_model}</style> │"
                    f"{card_bit}"
                    f"{task_bit}"
                    f" <style fg='#e0af68'>Ctrl+X</style> "
                )
            return self.HTML(
                f" <style fg='#e0af68'>{html.escape(self.mode_label())}</style> │"
                f"{card_bit}"
                f" <style fg='#e0af68'>Ctrl+X</style> "
            )
        except Exception:
            return self.HTML(" <b>Friday</b> │ /shortcuts ") if self.HTML else None

    def get_composer_title(self):
        # Frame title shows location + mode. Session/model/counts live in the
        # toolbar below, so they are not repeated here.
        shown = self.mode_label()
        if self.HTML is None:
            return f"{shown}"
        cwd_s, branch_s = self.workspace_bits()
        cols = shutil.get_terminal_size(fallback=(100, 24)).columns
        bits = []
        if cols >= 90:
            bits.append(f"<b>{html.escape(cwd_s)}</b>")
            if branch_s:
                bits.append(f'<style fg="#00ff00">git:{html.escape(branch_s)}</style>')
            bits.append(f'<style fg="#e0af68">{html.escape(shown)}</style>')
        elif cols >= 60:
            short_cwd = cwd_s.split("/")[-1] if "/" in cwd_s else (cwd_s.split("\\")[-1] if "\\" in cwd_s else cwd_s)
            bits.append(f"<b>{html.escape(short_cwd)}</b>")
            if branch_s:
                bits.append(f'<style fg="#00ff00">git:{html.escape(branch_s)}</style>')
            bits.append(f'<style fg="#e0af68">{html.escape(shown)}</style>')
        else:
            bits.append(f'<style fg="#e0af68">{html.escape(shown)}</style>')
        return self.HTML(" · ".join(bits))

    def feed_orb(self, kind: str, ev: dict) -> None:
        p = self.stack.get("presence")
        o = self.stack.get("orb")
        if p is None:
            return
        if kind == "state":
            p.on_state(ev)
        elif kind == "tts":
            p.on_tts(ev)
        elif kind == "mic":
            p.on_mic(ev)
        elif kind == "card":
            p.on_card(ev)
        elif kind == "resolved":
            p.on_resolved(ev)
        if o is not None:
            o.push(p)

    def on_state(self, ev: dict) -> None:
        self.feed_orb("state", ev)
        if ev.get("task_id") and self.ui_state["foreground"]:
            return
        phase = ev.get("phase")
        if phase == "thinking":
            self.renderer.on_thinking()
        elif phase == "token":
            self.renderer.on_token(ev.get("text") or "")
        elif phase == "stuck":
            self.renderer.on_stuck(ev.get("question") or "")
        elif phase == "idle":
            self.renderer.on_idle()
            self.store.save(self.master.history, self.mode)
        elif phase == "listening":
            console.print("[dim][listening][/dim]")
        elif phase == "speaking":
            console.print("[dim][speaking][/dim]")
        elif phase == "waking":
            console.print("[dim][waking][/dim]")

    def on_tool_call(self, ev: dict) -> None:
        if ev.get("task_id") and self.ui_state["foreground"]:
            return
        self.renderer.on_tool_call(
            ev.get("name") or "",
            ev.get("args") or {},
            coerce_ring(ev.get("ring")),
            call_id=str(ev.get("id") or ""),
        )

    def on_tool_result(self, ev: dict) -> None:
        if ev.get("task_id") and self.ui_state["foreground"]:
            return
        self.renderer.on_tool_result(
            ev.get("name") or "",
            ev.get("result") or "",
            call_id=str(ev.get("id") or ""),
        )

    async def on_card(self, ev: dict) -> None:
        from ui.render.cards import render_card

        self.feed_orb("card", ev)
        self.renderer.on_card()
        render_card(ev)
        cid = ev.get("id", "")
        if not self.ui_state["foreground"] or cid not in self.gate.pending():
            return
        if self.ui_state.get("prompt_up"):
            return
        kind = ev.get("kind", "permission")
        if kind == "question":
            options = ev.get("options") or []
            try:
                from prompt_toolkit import PromptSession

                hint = f"1-{len(options)}" if options else "text"
                choice = await PromptSession().prompt_async(
                    self.HTML(f'<style fg="#89b4fa">  choice [{hint} or custom]:</style> ')
                    if self.HTML
                    else f"  choice [{hint} or custom]: "
                )
            except (EOFError, KeyboardInterrupt, Exception):
                choice = "1"
            if cid in self.gate.pending():
                raw = str(choice).strip()
                if raw.isdigit() and 1 <= int(raw) <= len(options):
                    selected = options[int(raw) - 1]
                elif raw.lower() == "c" or not raw:
                    selected = options[0] if options else "cancelled"
                else:
                    selected = raw
                self.gate.resolve(cid, selected)
                console.print(f"[bold #a6e3a1]selected:[/bold #a6e3a1] {selected}")
            return

        try:
            from prompt_toolkit import PromptSession

            choice = await PromptSession().prompt_async(
                self.HTML('<style fg="#f38ba8">  allow?</style> <style fg="#6c7086">[y/n/1/2]</style> ')
                if self.HTML
                else "  allow? [y/n/1/2] "
            )
        except (EOFError, KeyboardInterrupt, Exception):
            choice = "n"
        if cid in self.gate.pending():
            raw = str(choice).strip().lower()
            ok = raw in ("1", "y", "yes", "a", "allow") or raw.startswith("1.") or raw.startswith("/approve")
            self.gate.resolve(cid, ok)
            console.print("[green]allowed[/green]" if ok else "[yellow]denied[/yellow]")

    def on_resolved(self, ev: dict) -> None:
        self.feed_orb("resolved", ev)
        if not ev.get("expired"):
            return
        cid = ev.get("id", "")
        if "answer" in ev:
            fate = f"selected default '{ev.get('answer')}'"
        else:
            fate = "allowed" if ev.get("approved") else "denied"
        console.print(f"[yellow]card {cid} expired → {fate}[/yellow]")

    def on_error(self, ev: dict) -> None:
        console.print(f"\n[bold red]error[/bold red] {ev.get('error')}")

    async def watch(self, topic: str, handler) -> None:
        q = self.bus.subscribe(topic)
        while True:
            result = handler(await q.get())
            if asyncio.iscoroutine(result):
                await result

    async def read_line(self) -> str:
        self.ui_state["prompt_up"] = True
        try:
            if self.session:
                from ui.composer import Composer

                if isinstance(self.session, Composer):
                    return await self.session.prompt_async()
                cwd_s, branch_s = self.workspace_bits()
                return await self.session.prompt_async(
                    lambda: _friday_prompt(self.store, self.mode, cwd_s, branch_s),
                    placeholder=self.HTML('<style color="#6c6c6c">message, @file, or /command</style>') if self.HTML else None,
                )
            return await asyncio.to_thread(input, "Friday> ")
        finally:
            self.ui_state["prompt_up"] = False

    async def run_foreground(self, prompt: str, *, shown: str, skip_clarify: bool = False) -> None:
        from ui.render.inventory import render_user

        async with self.turn_lock:
            render_user(shown)
            self.master.mode = self.mode
            plan_path = self.root / "plan.md"
            before_plan = None
            if self.mode.lower() == "architect" and plan_path.is_file():
                try:
                    before_plan = plan_path.read_text(encoding="utf-8")
                except OSError:
                    before_plan = None
            if not self.session:
                asyncio.create_task(self.master.turn(prompt, skip_clarify=skip_clarify, mode=self.mode))
                return
            self.renderer.begin_turn()
            self.ui_state["foreground"] = True
            try:
                await self.master.turn(prompt, skip_clarify=skip_clarify, mode=self.mode)
            except (KeyboardInterrupt, asyncio.CancelledError):
                console.print("[yellow]turn cancelled[/yellow]")
            except Exception as exc:
                console.print(f"[bold red]error[/bold red] {exc}")
            finally:
                self.ui_state["foreground"] = False
                self.renderer.finish()
                self.store.save(self.master.history, self.mode)
                self.present_written_plan(before_plan)

    async def voice_turn(self, text: str) -> str:
        await self.run_foreground(text, shown=f"(voice) {text}")
        for msg in reversed(self.master.history):
            if msg.get("role") == "assistant":
                return str(msg.get("content") or "")
        return ""

    def on_orb_mute(self) -> None:
        v = self.stack.get("voice")
        p = self.stack.get("presence")
        o = self.stack.get("orb")
        if v is None:
            return
        v.muted = not v.muted
        if v.muted:
            v.stop_record()
        if p is not None:
            p.muted = v.muted
            if o is not None:
                o.push(p)

    def on_orb_sleep(self) -> None:
        v = self.stack.get("voice")
        p = self.stack.get("presence")
        o = self.stack.get("orb")
        if v is not None:
            v.muted = True
            v.stop_record()
            v.cancel()
        if p is not None:
            p.muted = True
        if o is not None:
            o.hide()
            if p is not None:
                o.push(p)

    def on_orb_close(self) -> None:
        o = self.stack.get("orb")
        if o is not None:
            o.stop()
        self.stack["orb"] = None

    def start_voice(self) -> None:
        voice_cfg = self.stack.get("voice_cfg") or {}
        if not (self.voice_flag or voice_cfg.get("enabled")):
            return
        from voice import EngineMissing, VoiceIO, make_stt, make_tts

        try:
            voice = VoiceIO(
                self.bus,
                voice_cfg,
                make_stt(voice_cfg),
                make_tts(voice_cfg),
                resolve_card=self.gate.resolve,
            )
            self.stack["voice"] = voice
            voice.start(self.voice_turn)
            wake = str((voice_cfg.get("wake_word") or {}).get("engine") or "none")
            extra = "" if wake == "none" else f"  wake {wake}"
            console.print(f"[dim]voice on[/dim]  /listen · click the orb{extra}")
            orb_cfg = voice_cfg.get("orb") or {}
            if orb_cfg.get("enabled", True):
                from orb import Overlay, Presence

                presence = Presence()
                overlay = Overlay(
                    size=int(orb_cfg.get("size") or 140),
                    width=int(orb_cfg["width"]) if orb_cfg.get("width") is not None else None,
                    height=int(orb_cfg["height"]) if orb_cfg.get("height") is not None else None,
                    on_toggle=voice.toggle_listen,
                    on_mute=self.on_orb_mute,
                    on_sleep=self.on_orb_sleep,
                    on_close=self.on_orb_close,
                )
                if overlay.start(asyncio.get_running_loop()):
                    self.stack["orb"] = overlay
                    self.stack["presence"] = presence
                    overlay.push(presence)
                    console.print("[dim]orb on[/dim]  click to talk · /orb hides")
                else:
                    console.print("[yellow]orb off[/yellow]  tkinter missing")
        except (EngineMissing, ValueError) as exc:
            console.print(f"[yellow]voice off[/yellow]  {exc}")

    async def run(self) -> None:
        try:
            from prompt_toolkit.formatted_text import HTML
            from prompt_toolkit.patch_stdout import patch_stdout
        except ImportError:
            HTML = None
            patch_stdout = None
        self.HTML = HTML

        from ui.render.banner import render_banner

        self.watchers = [
            asyncio.create_task(self.watch("agent.state", self.on_state)),
            asyncio.create_task(self.watch("tool.call", self.on_tool_call)),
            asyncio.create_task(self.watch("tool.result", self.on_tool_result)),
            asyncio.create_task(self.watch("approval.request", self.on_card)),
            asyncio.create_task(self.watch("approval.resolved", self.on_resolved)),
            asyncio.create_task(self.watch("error", self.on_error)),
            asyncio.create_task(self.watch("tts.amplitude", lambda ev: self.feed_orb("tts", ev))),
            asyncio.create_task(self.watch("mic.amplitude", lambda ev: self.feed_orb("mic", ev))),
        ]

        cwd_s, branch_s = self.workspace_bits()
        render_banner(
            model=self.master_model,
            mode=self.mode,
            cwd=cwd_s,
            branch=branch_s,
            session_id=self.store.id,
            title=self.store.title,
        )

        self.session = _create_prompt_session(
            lambda: self.stack,
            self.get_bottom_toolbar,
            self.get_composer_title,
            self._history_path,
            on_cycle_mode=self.cycle_mode,
            get_input_mode=self.input_mode,
        )
        self.start_voice()

        stdout_patch = None
        try:
            if patch_stdout:
                stdout_patch = patch_stdout(raw=True)
                stdout_patch.__enter__()
            while True:
                try:
                    line = await self.read_line()
                except (EOFError, KeyboardInterrupt):
                    break
                fate = await handle_line(self, line)
                if fate == "exit":
                    break
        finally:
            if stdout_patch is not None:
                try:
                    stdout_patch.__exit__(None, None, None)
                except Exception:
                    pass
            for w in self.watchers:
                w.cancel()
            if self.stack.get("orb") is not None:
                self.stack["orb"].stop()
            if self.stack.get("voice") is not None:
                await self.stack["voice"].stop()
            self.store.save(self.master.history, self.mode)
            self.stack["memory"].close()


async def run_cli(root: Path, *, voice_flag: bool = False) -> None:
    await Cli(root, voice_flag=voice_flag).run()
