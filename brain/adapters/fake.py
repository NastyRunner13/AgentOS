"""In-process adapter for tests. `script` maps model id → str | list | callable."""

from __future__ import annotations

import inspect
from typing import Any

from brain.adapters.compat import OnToken


class FakeAdapter:
    def __init__(self, cfg: dict | None = None) -> None:
        self.script: dict[str, Any] = dict((cfg or {}).get("script") or {})
        self.calls: list[tuple[str, list, list | None]] = []
        self.default = (cfg or {}).get("default", "ok")

    async def chat(self, model_id: str, messages: list[dict], tools, on_token: OnToken):
        self.calls.append((model_id, messages, tools))
        raw = self.script.get(model_id, self.default)
        if isinstance(raw, list):
            raw = raw.pop(0)
        if callable(raw):
            raw = raw(messages, tools)
        if inspect.isawaitable(raw):
            raw = await raw
        if isinstance(raw, tuple):
            text, tool_calls = raw
        else:
            text, tool_calls = str(raw), []
        if on_token and text:
            for i in range(0, len(text), 4):
                on_token(text[i : i + 4])
        return text, tool_calls

    async def embed(self, model_id: str, texts: list[str]) -> list[list[float]]:
        return [[float(len(t))] for t in texts]
