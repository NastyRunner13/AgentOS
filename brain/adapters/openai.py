"""OpenAI-compatible chat/embeddings (OpenRouter and OpenAI)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from brain.adapters.compat import OnToken, _secret, _timeout


def wire_messages(messages: list[dict]) -> list[dict]:
    """OpenAI-compatible payload: ids on tool_calls, null content, valid JSON args."""
    out: list[dict] = []
    for msg in messages:
        m = dict(msg)
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            if not m.get("content"):
                m["content"] = None
            calls = []
            for i, tc in enumerate(m["tool_calls"]):
                tc = dict(tc)
                if not str(tc.get("id") or "").strip():
                    tc["id"] = f"call_{i}"
                tc["type"] = tc.get("type") or "function"
                fn = dict(tc.get("function") or {})
                args = fn.get("arguments", "{}")
                if not isinstance(args, str):
                    args = json.dumps(args)
                else:
                    try:
                        json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = "{}"
                fn["arguments"] = args or "{}"
                tc["function"] = fn
                calls.append(tc)
            m["tool_calls"] = calls
        elif role == "tool":
            if not str(m.get("tool_call_id") or "").strip():
                m["tool_call_id"] = "call_0"
        out.append(m)
    return out


class OpenAICompat:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.base = str(cfg.get("base_url", "https://openrouter.ai/api/v1")).rstrip("/")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", **(self.cfg.get("headers") or {})}
        key = _secret(self.cfg)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def chat(self, model_id: str, messages: list[dict], tools, on_token: OnToken):
        body: dict[str, Any] = {
            "model": model_id,
            "messages": wire_messages(messages),
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        async with httpx.AsyncClient(timeout=_timeout(self.cfg)) as client:
            async with client.stream(
                "POST",
                f"{self.base}/chat/completions",
                json=body,
                headers=self._headers(),
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(f"{resp.status_code} {resp.text}")
                return await _consume_openai_sse(resp, on_token)

    async def embed(self, model_id: str, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=_timeout(self.cfg)) as client:
            resp = await client.post(
                f"{self.base}/embeddings",
                json={"model": model_id, "input": texts},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]


def _reasoning_piece(delta: dict) -> str:
    return str(delta.get("reasoning") or delta.get("reasoning_content") or "")


async def _consume_openai_sse(resp: httpx.Response, on_token: OnToken) -> tuple[str, list[dict]]:
    text = []
    calls: dict[int, dict] = {}
    reasoning_open = False
    async for line in resp.aiter_lines():
        if not line:
            continue
        if line.startswith(":") or not line.startswith("data:"):
            line_str = line.strip()
            if line_str.startswith("{") and "error" in line_str:
                try:
                    obj = json.loads(line_str)
                    if "error" in obj:
                        err_obj = obj["error"]
                        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                        raise RuntimeError(err_msg or "Model API error")
                except json.JSONDecodeError:
                    pass
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if "error" in chunk:
            err_obj = chunk["error"]
            err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
            raise RuntimeError(err_msg or "Model API error")
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            thought = _reasoning_piece(delta)
            if thought:
                if not reasoning_open:
                    reasoning_open = True
                    if on_token:
                        on_token("<think>")
                if on_token:
                    on_token(thought)
            piece = delta.get("content")
            if piece:
                if reasoning_open:
                    reasoning_open = False
                    if on_token:
                        on_token("</think>")
                text.append(piece)
                if on_token:
                    on_token(piece)
            for tc in delta.get("tool_calls") or []:
                idx = int(tc.get("index", 0))
                slot = calls.setdefault(
                    idx,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
    if reasoning_open and on_token:
        on_token("</think>")
    ordered = [calls[i] for i in sorted(calls)]
    return "".join(text), ordered

