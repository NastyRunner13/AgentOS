"""Anthropic Messages API adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from brain.compat import OnToken, _secret, _timeout


class AnthropicAdapter:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.base = str(cfg.get("base_url", "https://api.anthropic.com")).rstrip("/")

    def _headers(self) -> dict:
        key = _secret(self.cfg)
        return {
            "Content-Type": "application/json",
            "x-api-key": key or "",
            "anthropic-version": str(self.cfg.get("api_version", "2023-06-01")),
        }

    async def chat(self, model_id: str, messages: list[dict], tools, on_token: OnToken):
        system, converted = _to_anthropic_messages(messages)
        body: dict[str, Any] = {
            "model": model_id,
            "messages": converted,
            "max_tokens": int(self.cfg.get("max_tokens", 4096)),
            "stream": True,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters") or {"type": "object"},
                }
                for t in tools
            ]
        text = []
        calls: dict[int, dict] = {}
        async with httpx.AsyncClient(timeout=_timeout(self.cfg)) as client:
            async with client.stream(
                "POST",
                f"{self.base}/v1/messages",
                json=body,
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(f"{resp.status_code} {resp.text}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[5:].strip())
                    ptype = payload.get("type")
                    if ptype == "content_block_delta":
                        delta = payload.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            text.append(delta["text"])
                            if on_token:
                                on_token(delta["text"])
                        if delta.get("type") == "input_json_delta":
                            idx = int(payload.get("index", 0))
                            slot = calls.setdefault(
                                idx,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            slot["function"]["arguments"] += delta.get("partial_json") or ""
                    elif ptype == "content_block_start":
                        block = payload.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = int(payload.get("index", 0))
                            calls[idx] = {
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                },
                            }
        return "".join(text), [calls[i] for i in sorted(calls)]


def _to_anthropic_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    system_parts = []
    out: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            system_parts.append(str(msg.get("content") or ""))
            continue
        if role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": str(msg.get("content") or ""),
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and msg.get("tool_calls"):
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            for tc in msg["tool_calls"]:
                try:
                    inp = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    inp = {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "input": inp,
                    }
                )
            out.append({"role": "assistant", "content": content})
            continue
        out.append({"role": role, "content": msg.get("content") or ""})
    return "\n".join(system_parts), out
