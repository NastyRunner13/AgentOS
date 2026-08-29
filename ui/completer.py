"""Slash-command auto-completer for the Friday interactive terminal."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

SLASH_COMMANDS: dict[str, str] = {
    "/new": "Start a fresh conversation (saves the current one)",
    "/reset": "Alias for /new",
    "/resume": "Resume a previous session: /resume [id]",
    "/sessions": "List saved conversations",
    "/rename": "Rename the current session: /rename <title>",
    "/mode": "Switch agent mode (Code, Architect, Ask, Fast)",
    "/provider": "Select LLM provider & default model",
    "/skills": "Browse available agent skills & procedures",
    "/plugins": "View active tool specs & integrations",
    "/settings": "Adjust runtime parameters (clarify, max steps, slots)",
    "/facts": "View confirmed long-term memory facts",
    "/proposals": "View pending Librarian memory proposals",
    "/consolidate": "Trigger Librarian consolidation draft",
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
    "/quit": "Exit Friday",
}

_MODE_NAMES = ("Code", "Architect", "Ask", "Fast")


class FridayCommandCompleter(Completer):
    """Provides floating popup autocompletion with command descriptions."""

    def __init__(self, stack_getter: Optional[Callable[[], dict[str, Any]]] = None) -> None:
        self.stack_getter = stack_getter

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text = document.text_before_cursor
        
        # If user is at root prompt and typing a slash command
        if text.startswith("/"):
            # Check for sub-arguments completion (e.g. /approve <id>, /deny <id>, /steer <id>)
            parts = text.split(" ", 1)
            cmd = parts[0]
            
            if len(parts) == 2 and self.stack_getter:
                arg_prefix = parts[1]
                try:
                    stack = self.stack_getter()
                except Exception:
                    stack = {}

                if cmd in ("/approve", "/deny"):
                    # Suggest pending card IDs and proposal IDs
                    gate = stack.get("gate")
                    memory = stack.get("memory")
                    
                    if cmd == "/approve" and "all".startswith(arg_prefix.lower()):
                        yield Completion("all", start_position=-len(arg_prefix), display="all", display_meta="Approve all memory proposals")

                    if gate and hasattr(gate, "pending"):
                        try:
                            cards = gate.pending()
                            for cid in cards:
                                if isinstance(cid, str) and cid.startswith(arg_prefix):
                                    yield Completion(
                                        cid,
                                        start_position=-len(arg_prefix),
                                        display=cid,
                                        display_meta="Security Card",
                                    )
                        except Exception:
                            pass
                    if memory and hasattr(memory, "pending"):
                        try:
                            for p in memory.pending():
                                pid = p.get("id", "")
                                if pid.startswith(arg_prefix):
                                    payload = p.get("payload", {})
                                    preview = payload.get("statement") or payload.get("name") or str(payload)
                                    yield Completion(
                                        pid,
                                        start_position=-len(arg_prefix),
                                        display=pid,
                                        display_meta=f"Proposal ({p.get('kind')}): {preview[:30]}",
                                    )
                        except Exception:
                            pass
                    return

                if cmd == "/steer":
                    tasks = stack.get("tasks")
                    if tasks and hasattr(tasks, "tasks"):
                        for tid, t in tasks.tasks.items():
                            if tid.startswith(arg_prefix):
                                yield Completion(
                                    tid,
                                    start_position=-len(arg_prefix),
                                    display=tid,
                                    display_meta=f"Task [{t.status}]: {t.title[:30]}",
                                )
                    return

                if cmd == "/resume":
                    store = stack.get("sessions")
                    if store and hasattr(store, "list"):
                        for row in store.list():
                            sid = str(row.get("id", ""))
                            title = str(row.get("title") or "(untitled)")
                            if sid.startswith(arg_prefix) or arg_prefix.lower() in title.lower():
                                yield Completion(
                                    sid,
                                    start_position=-len(arg_prefix),
                                    display=sid,
                                    display_meta=title[:40],
                                )
                    return

                if cmd == "/mode":
                    for name in _MODE_NAMES:
                        if name.lower().startswith(arg_prefix.lower()):
                            yield Completion(
                                name,
                                start_position=-len(arg_prefix),
                                display=name,
                                display_meta="Agent mode",
                            )
                    return

            # Complete the root command
            word = text
            for command, desc in SLASH_COMMANDS.items():
                if command.startswith(word):
                    yield Completion(
                        command,
                        start_position=-len(word),
                        display=command,
                        display_meta=desc,
                    )
