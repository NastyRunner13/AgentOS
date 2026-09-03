"""Master agent: clarify-first, tool loop, cards via the gate, steer drain."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from pathlib import Path
from typing import Any, Callable

from brain.librarian import draft
from brain.registry import Registry
from kernel import Bus, Gate, Task, TaskManager
from memory import Episodic
from tools import SPECS, NativeTools
from tools.files import is_plan_path

ARCHITECT_TOOLS = frozenset(
    {"files", "web_search", "web_fetch", "kb_read", "skill", "ask_user"}
)
ARCHITECT_BLOCK = "architect mode forbids this tool; write only plan.md"
OBSERVE_COMPUTER = frozenset({"see", "snapshot", "list_windows"})
COMPUTER_MUTATE = frozenset({"click", "type", "keys", "scroll", "open", "close", "focus"})
SERIAL_ALONE = frozenset({"skill", "ask_user", "browser", "kb_consolidate"})

OnToken = Callable[[str], None]


def _json_object(text: str) -> dict | None:
    text = text.strip()
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        val = json.loads(match.group(0))
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        return None


def _with_call_ids(calls: list[dict]) -> list[dict]:
    out = []
    for i, call in enumerate(calls):
        c = dict(call)
        if not str(c.get("id") or "").strip():
            c["id"] = f"call_{i}"
        c["type"] = c.get("type") or "function"
        c["function"] = dict(c.get("function") or {})
        out.append(c)
    return out


def _flatten_tool_turns(conv: list[dict]) -> list[dict]:
    """Drop native tool_calls so a provider that 404s on role=tool can still answer."""
    out: list[dict] = []
    for msg in conv:
        role = msg.get("role")
        if role == "tool":
            name = msg.get("name") or "tool"
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(
                    str(p.get("text") or "") for p in content if isinstance(p, dict)
                )
            out.append({"role": "user", "content": f"[{name} result]\n{content}"})
        elif role == "assistant" and msg.get("tool_calls"):
            names = [
                ((tc.get("function") or {}).get("name") or "tool") for tc in msg["tool_calls"]
            ]
            text = (msg.get("content") or "").strip()
            called = f"[called {', '.join(names)}]"
            out.append(
                {"role": "assistant", "content": f"{text}\n{called}".strip() if text else called}
            )
        else:
            out.append({k: v for k, v in msg.items() if k != "tool_calls"})
    out.append(
        {
            "role": "user",
            "content": "The tools already ran. Answer from the tool results above. Do not call tools.",
        }
    )
    return out


def _billed_calls(calls: list[dict]) -> bool:
    for call in calls:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        action = str(_parse_args(fn.get("arguments", "")).get("action") or "")
        if name != "computer" or action not in OBSERVE_COMPUTER:
            return True
    return False


def _parse_args(raw: str) -> dict:
    raw = (raw or "").strip() or "{}"
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _norm_path(raw: str) -> str:
    return str(raw or "").replace("\\", "/").strip().lower()


def _isolation_keys(name: str, args: dict) -> set[str]:
    keys: set[str] = set()
    if name == "files":
        for key in ("path", "dest"):
            path = _norm_path(str(args.get(key) or ""))
            if path:
                keys.add(f"files:{path}")
    if name == "computer":
        keys.add("computer")
    return keys


def _runs_alone(name: str, action: str, ring: int) -> bool:
    if ring >= 2:
        return True
    if name in SERIAL_ALONE:
        return True
    if name == "computer" and action in COMPUTER_MUTATE:
        return True
    return False


def _tool_groups(calls: list[dict], classify) -> list[list[dict]]:
    """Split a model step into gather-able groups. Serial-alone calls are singletons."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_keys: set[str] = set()

    def flush() -> None:
        nonlocal current, current_keys
        if current:
            groups.append(current)
        current = []
        current_keys = set()

    for call in calls:
        fn = call.get("function") or {}
        name = fn.get("name") or ""
        args = _parse_args(fn.get("arguments", ""))
        action = str(args.get("action") or "")
        ring = int(classify(name, args))
        keys = _isolation_keys(name, args)
        if _runs_alone(name, action, ring):
            flush()
            groups.append([call])
            continue
        if current_keys & keys:
            flush()
        current.append(call)
        current_keys |= keys
    flush()
    return groups


def _attach_screen(conv: list[dict], result: str) -> None:
    obj = _json_object(result)
    if not obj:
        return
    raw = obj.get("screenshot")
    if not raw:
        return
    path = Path(str(raw))
    if not path.is_file():
        return
    data = path.read_bytes()
    if not data or len(data) > 4_000_000:
        return
    conv.append(
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        '<untrusted source="screen">x,y for computer click/type/keys/scroll '
                        "are 0-1000 on this image (0,0 top-left, 1000,1000 bottom-right). "
                        "Do not convert into pixel width/height. "
                        "A red crosshair is the last click if present.</untrusted>"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"},
                },
            ],
        }
    )


class Master:
    def __init__(
        self,
        registry: Registry,
        gate: Gate,
        tasks: TaskManager,
        memory: Episodic,
        tools: NativeTools,
        bus: Bus,
        *,
        system_prompt: str,
        clarify_prompt: str,
        clarify: bool = True,
        max_tool_steps: int = 8,
        secrets: list[str] | None = None,
        skills: list | None = None,
        architect_prompt: str = "",
    ) -> None:
        self.registry = registry
        self.gate = gate
        self.tasks = tasks
        self.memory = memory
        self.tools = tools
        self.bus = bus
        self.system_prompt = system_prompt
        self.clarify_prompt = clarify_prompt
        self.architect_prompt = architect_prompt
        self.clarify = clarify
        self.max_tool_steps = max_tool_steps
        self.secrets = [s for s in (secrets or []) if s]
        self.skills = skills or []
        self.history: list[dict] = []
        self.mode = "Code"
        self._turn_mode = "Code"
        self._awaiting_clarify = False
        self._active_skill = None

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text

    def scrub_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.scrub(obj)
        if isinstance(obj, dict):
            return {k: self.scrub_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.scrub_obj(v) for v in obj]
        return obj

    async def drain_steer(self, task: Task | None, conv: list[dict]) -> list[str]:
        got = []
        if task is None:
            return got
        while True:
            try:
                msg = task.inbox.get_nowait()
            except asyncio.QueueEmpty:
                break
            got.append(msg)
            conv.append({"role": "user", "content": f"[steer] {msg}"})
            self.memory.write("steer", content=self.scrub(msg), role="user", meta={"task_id": task.id})
        return got

    async def turn(
        self,
        text: str,
        task: Task | None = None,
        on_token: OnToken | None = None,
        *,
        skip_clarify: bool = False,
        mode: str | None = None,
    ) -> str:
        if task is not None and mode is None:
            self._turn_mode = "Code"
        else:
            self._turn_mode = mode or self.mode or "Code"
        text = self.scrub(text)
        self.memory.write("turn", content=text, role="user", meta={"task_id": task.id if task else None})
        self.bus.publish("agent.state", {"phase": "thinking", "task_id": task.id if task else None})

        if skip_clarify:
            self._awaiting_clarify = False
        elif self.clarify and task is None and self._awaiting_clarify:
            self._awaiting_clarify = False
        elif self.clarify:
            decision = await self._clarify(text, use_history=task is None)
            if decision.get("clarity") == "unclear":
                question = decision.get("question")
                options = decision.get("options") or []
                if not question and decision.get("questions"):
                    question = decision["questions"][0]

                if options and task is None and hasattr(self.gate, "ask"):
                    answer = await self.gate.ask(question or "Clarification needed", options)
                    text = f"{text}\n\n[clarification: {question} -> {answer}]"
                else:
                    questions = decision.get("questions") or [question or "What did you mean?"]
                    reply = "I need a bit more:\n" + "\n".join(f"- {q}" for q in questions[:3])
                    self._emit_text(reply, on_token, task.id if task else None)
                    self.memory.write("turn", content=reply, role="assistant", meta={"task_id": task.id if task else None})
                    if task is None:
                        self._awaiting_clarify = True
                        self.history.append({"role": "user", "content": text})
                        self.history.append({"role": "assistant", "content": reply})
                    self.bus.publish("agent.state", {"phase": "idle", "task_id": task.id if task else None})
                    return reply
            if decision.get("clarity") == "trivial" and decision.get("assumption"):
                text = f"{text}\n\n[assumption] {decision['assumption']}"

        conv: list[dict] = [{"role": "system", "content": self._system_with_facts(text)}]
        if task is None:
            conv.extend(self.history)
        conv.append({"role": "user", "content": text})

        self._active_skill = self._skill_from_turn(text)
        try:
            reply = await self._loop(conv, task, on_token)
        finally:
            self._active_skill = None
        if task is None:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": reply})
        self.memory.write("turn", content=reply, role="assistant", meta={"task_id": task.id if task else None})
        self.bus.publish("agent.state", {"phase": "idle", "task_id": task.id if task else None})
        return reply

    def _skill_from_turn(self, text: str):
        if not text.startswith("[skill:"):
            return None
        from brain.skills import find_skill

        end = text.find("]", 7)
        if end < 0:
            return None
        return find_skill(text[7:end], self.skills)

    async def _clarify(self, text: str, *, use_history: bool = True) -> dict:
        messages = [{"role": "system", "content": self.clarify_prompt}]
        if use_history:
            messages.extend(self.history[-6:])
        messages.append({"role": "user", "content": text})
        try:
            raw, _ = await self.registry.complete("fast", messages)
        except Exception:
            return {"clarity": "clear"}
        return _json_object(raw) or {"clarity": "clear"}

    def _system_with_facts(self, query: str) -> str:
        prompt = self.system_prompt
        if (self._turn_mode or "").lower() == "architect" and self.architect_prompt:
            prompt = f"{prompt}\n\n{self.architect_prompt}"
        if hasattr(self.tools, "root") and self.tools.root:
            prompt = f"{prompt}\n\nCurrent workspace root directory: {self.tools.root}"
        if self.skills:
            from brain.skills import format_skills_for_prompt
            skills_block = format_skills_for_prompt(self.skills)
            if skills_block:
                prompt = f"{prompt}\n\n{skills_block}"
        facts = self.memory.recall(query)
        if not facts:
            return prompt
        lines = "\n".join(f"- {f['statement']}" for f in facts)
        return f"{prompt}\n\nConfirmed facts (user-approved):\n{lines}"

    async def _loop(self, conv: list[dict], task: Task | None, on_token: OnToken | None) -> str:
        last = ""
        billed = 0
        rounds = 0
        max_rounds = max(self.max_tool_steps * 2, self.max_tool_steps)
        while billed < self.max_tool_steps and rounds < max_rounds:
            rounds += 1
            await self.drain_steer(task, conv)
            streamed: list[str] = []

            def capture(piece: str) -> None:
                streamed.append(piece)
                self._emit_text(piece, on_token, task.id if task else None)

            try:
                text, calls = await self.registry.complete(
                    "master", conv, tools=SPECS, on_token=capture
                )
            except Exception as exc:
                err = self.scrub(str(exc))
                if any(m.get("role") == "tool" for m in conv):
                    try:
                        text, _ignored = await self.registry.complete(
                            "master",
                            _flatten_tool_turns(conv),
                            tools=None,
                            on_token=capture,
                        )
                    except Exception as exc2:
                        err = self.scrub(str(exc2))
                    else:
                        if not streamed and text:
                            self._emit_text(text, on_token, task.id if task else None)
                        return text or last
                self.bus.publish("error", {"error": err})
                return f"model error: {err}"
            last = text
            calls = _with_call_ids(calls) if calls else []
            steered = await self.drain_steer(task, conv)
            if not calls and not steered:
                if not streamed and text:
                    self._emit_text(text, on_token, task.id if task else None)
                return text
            conv.append(
                {
                    "role": "assistant",
                    "content": text or "",
                    **({"tool_calls": calls} if calls else {}),
                }
            )
            if not calls:
                billed += 1
                continue
            ordered = sorted(
                calls,
                key=lambda c: 0 if (c.get("function") or {}).get("name") == "skill" else 1,
            )
            await self._execute_calls(ordered, conv, task)
            if _billed_calls(ordered):
                billed += 1
        return last or "hit max tool steps"

    async def _execute_calls(
        self, calls: list[dict], conv: list[dict], task: Task | None
    ) -> None:
        executed_gui_action = False
        skip_gui = json.dumps(
            {
                "error": "Screen state changed after previous action. Re-inspect screen (see/snapshot) before issuing further actions.",
                "verified": False,
            }
        )
        for group in _tool_groups(calls, self.gate.classify):
            results: dict[str, str] = {}
            skipped: set[str] = set()
            runnable: list[dict] = []
            for call in group:
                fn_name = (call.get("function") or {}).get("name") or ""
                action = str(_parse_args((call.get("function") or {}).get("arguments", "")).get("action") or "")
                cid = str(call.get("id") or "")
                if executed_gui_action and fn_name == "computer" and action in COMPUTER_MUTATE:
                    results[cid] = skip_gui
                    skipped.add(cid)
                else:
                    runnable.append(call)
            if len(runnable) == 1:
                results[str(runnable[0].get("id") or "")] = await self._run_tool(runnable[0], task)
            elif runnable:
                gathered = await asyncio.gather(
                    *[self._run_tool(c, task) for c in runnable],
                    return_exceptions=True,
                )
                for call, result in zip(runnable, gathered):
                    cid = str(call.get("id") or "")
                    if isinstance(result, BaseException):
                        err = f"tool error: {self.scrub(str(result))}"
                        results[cid] = err
                        fn_name = (call.get("function") or {}).get("name") or ""
                        self.bus.publish(
                            "tool.result",
                            {
                                "id": cid,
                                "name": fn_name,
                                "result": err[:500],
                                "task_id": task.id if task else None,
                            },
                        )
                    else:
                        results[cid] = result
            for call in group:
                fn_name = (call.get("function") or {}).get("name") or ""
                action = str(_parse_args((call.get("function") or {}).get("arguments", "")).get("action") or "")
                cid = str(call.get("id") or "")
                result = results.get(cid, "")
                conv.append(
                    {
                        "role": "tool",
                        "tool_call_id": cid,
                        "name": fn_name,
                        "content": self.scrub(result),
                    }
                )
                if fn_name == "computer" and cid not in skipped:
                    _attach_screen(conv, result)
                    if action in COMPUTER_MUTATE:
                        executed_gui_action = True

    async def _run_tool(self, call: dict, task: Task | None) -> str:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = _parse_args(fn.get("arguments", ""))
        if name == "files" and args.get("action") == "delete":
            args["_size"] = self.tools.file_size(str(args.get("path", "")))
        self.bus.publish(
            "tool.call",
            {
                "id": call.get("id") or "",
                "name": name,
                "args": args,
                "ring": self.gate.classify(name, args),
                "task_id": task.id if task else None,
            },
        )
        blocked = ""
        if (
            self._active_skill
            and self._active_skill.allowed_tools
            and name not in self._active_skill.allowed_tools
        ):
            blocked = "skill forbids this tool"
        else:
            blocked = self._architect_blocks(name, args)
        if blocked:
            result = blocked
            self.memory.write("tool", content=self.scrub(result), role=name, meta={"args": self.scrub_obj(args), "denied": True})
            self.bus.publish(
                "tool.result",
                {
                    "id": call.get("id") or "",
                    "name": name,
                    "result": self.scrub(result),
                    "task_id": task.id if task else None,
                },
            )
            return result
        if task:
            task.status = "waiting_approval" if self.gate.classify(name, args) >= 2 else "running"
            self.bus.publish("task.update", task.as_dict())
        ok = await self.gate.check(name, args)
        if task and task.status == "waiting_approval":
            task.status = "running"
            self.bus.publish("task.update", task.as_dict())
        if not ok:
            result = "denied"
        elif name == "spawn_task":
            title = str(args.get("title") or "task")
            prompt = str(args.get("prompt") or "")

            async def factory(bg: Task) -> None:
                await self.turn(prompt, task=bg)

            spawned = self.tasks.spawn(title, factory)
            result = f"spawned {spawned.id}"
        elif name == "kb_read":
            result = json.dumps(self.memory.recall(str(args.get("query") or "")))
        elif name == "kb_propose":
            pid = self.memory.propose(args)
            result = f"proposed {pid} (pending approval)" if pid else "duplicate or invalid proposal"
        elif name == "kb_consolidate":
            result = json.dumps(await draft(self.memory, self.registry, self.bus))
        elif name == "skill":
            result = self._load_skill(str(args.get("name") or ""))
        elif name == "ask_user":
            question = str(args.get("question") or "")
            options = list(args.get("options") or [])
            if not options:
                options = ["Proceed", "Cancel"]
            if hasattr(self.gate, "ask"):
                answer = await self.gate.ask(question, options)
                result = f"User selected: {answer}"
            else:
                result = f"User selected: {options[0]}"
        else:
            result = await self.tools.execute(name, args)
        self.memory.write(
            "tool",
            content=self.scrub(result),
            role=name,
            meta={"args": self.scrub_obj(args), "denied": not ok},
        )
        self.bus.publish(
            "tool.result",
            {
                "id": call.get("id") or "",
                "name": name,
                "result": self.scrub(result)[:500],
                "task_id": task.id if task else None,
            },
        )
        return result

    def _architect_blocks(self, name: str, args: dict) -> str:
        if (self._turn_mode or "").lower() != "architect":
            return ""
        if name not in ARCHITECT_TOOLS:
            return ARCHITECT_BLOCK
        if name != "files":
            return ""
        action = str(args.get("action") or "read")
        if action in ("read", "search"):
            return ""
        if action == "write" and is_plan_path(str(args.get("path") or ""), self.tools.root):
            return ""
        return ARCHITECT_BLOCK

    def _load_skill(self, name: str) -> str:
        from brain.skills import find_skill

        skill = find_skill(name, self.skills)
        if skill is None or skill.disable_model_invocation:
            return f"unknown skill {name}"
        self._active_skill = skill
        return skill.content or f"skill {skill.name} has an empty body"

    def _emit_text(self, piece: str, on_token: OnToken | None, task_id: str | None = None) -> None:
        self.bus.publish("agent.state", {"phase": "token", "text": piece, "task_id": task_id})
        if on_token:
            on_token(piece)
