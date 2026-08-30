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

        reply = await self._loop(conv, task, on_token)
        if task is None:
            self.history.append({"role": "user", "content": text})
            self.history.append({"role": "assistant", "content": reply})
        self.memory.write("turn", content=reply, role="assistant", meta={"task_id": task.id if task else None})
        self.bus.publish("agent.state", {"phase": "idle", "task_id": task.id if task else None})
        return reply

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
                self.bus.publish("error", {"error": err})
                return f"model error: {err}"
            last = text
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
            for call in calls:
                result = await self._run_tool(call, task)
                conv.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
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
        self.bus.publish("tool.call", {"name": name, "args": args, "ring": self.gate.classify(name, args)})
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
        else:
            result = await self.tools.execute(name, args)
        self.memory.write("tool", content=result, role=name, meta={"args": args, "denied": not ok})
        self.bus.publish("tool.result", {"name": name, "result": self.scrub(result)[:500]})
        return result

    def _emit_text(self, piece: str, on_token: OnToken | None, task_id: str | None = None) -> None:
        self.bus.publish("agent.state", {"phase": "token", "text": piece, "task_id": task_id})
        if on_token:
            on_token(piece)
