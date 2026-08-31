"""Master agent: clarify-first, tool loop, cards via the gate, steer drain."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

from brain.librarian import draft
from brain.registry import Registry
from kernel import Bus, Gate, Task, TaskManager
from memory import Episodic
from tools import SPECS, NativeTools

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
            out.append({"role": "user", "content": f"[{name} result]\n{msg.get('content') or ''}"})
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


def _parse_args(raw: str) -> dict:
    raw = (raw or "").strip() or "{}"
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


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
    ) -> None:
        self.registry = registry
        self.gate = gate
        self.tasks = tasks
        self.memory = memory
        self.tools = tools
        self.bus = bus
        self.system_prompt = system_prompt
        self.clarify_prompt = clarify_prompt
        self.clarify = clarify
        self.max_tool_steps = max_tool_steps
        self.secrets = [s for s in (secrets or []) if s]
        self.skills = skills or []
        self.history: list[dict] = []
        self._awaiting_clarify = False
        self._active_skill = None

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text

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
            self.memory.write("steer", content=msg, role="user", meta={"task_id": task.id})
        return got

    async def turn(
        self,
        text: str,
        task: Task | None = None,
        on_token: OnToken | None = None,
        *,
        skip_clarify: bool = False,
    ) -> str:
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
                questions = decision.get("questions") or ["What did you mean?"]
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
        for _ in range(self.max_tool_steps):
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
                continue
            ordered = sorted(
                calls,
                key=lambda c: 0 if (c.get("function") or {}).get("name") == "skill" else 1,
            )
            for call in ordered:
                result = await self._run_tool(call, task)
                conv.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": (call.get("function") or {}).get("name") or "",
                        "content": self.scrub(result),
                    }
                )
        return last or "hit max tool steps"

    async def _run_tool(self, call: dict, task: Task | None) -> str:
        fn = call.get("function") or {}
        name = fn.get("name", "")
        args = _parse_args(fn.get("arguments", ""))
        if name == "files" and args.get("action") == "delete":
            args["_size"] = self.tools.file_size(str(args.get("path", "")))
        self.bus.publish(
            "tool.call",
            {
                "name": name,
                "args": args,
                "ring": self.gate.classify(name, args),
                "task_id": task.id if task else None,
            },
        )
        if (
            self._active_skill
            and self._active_skill.allowed_tools
            and name not in self._active_skill.allowed_tools
        ):
            result = "skill forbids this tool"
            self.memory.write("tool", content=result, role=name, meta={"args": args, "denied": True})
            self.bus.publish(
                "tool.result",
                {
                    "name": name,
                    "result": result,
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
        else:
            result = await self.tools.execute(name, args)
        self.memory.write("tool", content=result, role=name, meta={"args": args, "denied": not ok})
        self.bus.publish(
            "tool.result",
            {
                "name": name,
                "result": self.scrub(result)[:500],
                "task_id": task.id if task else None,
            },
        )
        return result

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
