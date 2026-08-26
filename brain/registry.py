"""Model registry. Roles resolve through YAML; adapters speak one chat() shape."""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Callable, Optional

import httpx

OnToken = Optional[Callable[[str], None]]


class Registry:
    def __init__(self, cfg: dict, extra: dict | None = None) -> None:
        self.cfg = cfg
        self._extra = extra or {}

    def resolve(self, role: str) -> tuple[str, str, dict]:
        """Return (provider_name, model_id, provider_cfg)."""
        roles = self.cfg.get("roles") or {}
        if role not in roles:
            raise KeyError(f"unknown role {role!r}; defined: {sorted(roles)}")
        target = roles[role]
        if isinstance(target, dict):
            provider = target.get("provider") or self.cfg.get("default_provider", "openrouter")
            model_id = target["id"]
        else:
            model_id = str(target)
            catalog = (self.cfg.get("models") or {}).get(model_id) or {}
            provider = catalog.get("provider") or self.cfg.get("default_provider", "openrouter")
            model_id = catalog.get("id") or model_id
        providers = self.cfg.get("providers") or {}
        if provider not in providers and provider not in self._extra:
            raise KeyError(f"unknown provider {provider!r}")
        return provider, model_id, providers.get(provider) or {}

    async def complete(
        self,
        role: str,
        messages: list[dict],
        tools: list | None = None,
        on_token: OnToken = None,
    ) -> tuple[str, list[dict]]:
        provider, model_id, pcfg = self.resolve(role)
        adapter = self._adapter(provider, pcfg)
        return await adapter.chat(model_id, messages, tools, on_token)

    async def embed(self, texts: list[str], role: str = "embeddings") -> list[list[float]]:
        provider, model_id, pcfg = self.resolve(role)
        adapter = self._adapter(provider, pcfg)
        if not hasattr(adapter, "embed"):
            raise RuntimeError(f"provider {provider} has no embeddings")
        return await adapter.embed(model_id, texts)

    def _adapter(self, provider: str, pcfg: dict):
        if provider in self._extra:
            return self._extra[provider]
        kind = pcfg.get("kind", provider)
        if kind in ("openrouter", "openai"):
            return OpenAICompat(pcfg)
        if kind == "anthropic":
            return AnthropicAdapter(pcfg)
        if kind == "ollama":
            return OllamaAdapter(pcfg)
        if kind == "fake":
            return FakeAdapter(pcfg)
        raise KeyError(f"no adapter for provider {provider!r}")


def _secret(pcfg: dict) -> str | None:
    env = pcfg.get("api_key_env")
    if not env:
        return None
    key = os.environ.get(env)
    if not key:
        raise RuntimeError(f"missing env {env} — set it in .env")
    return key


def _timeout(pcfg: dict) -> httpx.Timeout:
    seconds = float(pcfg.get("timeout_seconds", 120))
    return httpx.Timeout(seconds, connect=10.0)


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
        body: dict[str, Any] = {"model": model_id, "messages": messages, "stream": True}
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


async def _consume_openai_sse(resp: httpx.Response, on_token: OnToken) -> tuple[str, list[dict]]:
    text = []
    calls: dict[int, dict] = {}
    async for line in resp.aiter_lines():
        if not line:
            continue
        if line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
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
    ordered = [calls[i] for i in sorted(calls)]
    return "".join(text), ordered


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


class OllamaAdapter:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.base = str(cfg.get("base_url", "http://localhost:11434")).rstrip("/")

    async def chat(self, model_id: str, messages: list[dict], tools, on_token: OnToken):
        body: dict[str, Any] = {"model": model_id, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        text = []
        calls: list[dict] = []
        async with httpx.AsyncClient(timeout=_timeout(self.cfg)) as client:
            async with client.stream("POST", f"{self.base}/api/chat", json=body) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                    raise RuntimeError(f"{resp.status_code} {resp.text}")
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    msg = chunk.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        text.append(piece)
                        if on_token:
                            on_token(piece)
                    for tc in msg.get("tool_calls") or []:
                        fn = tc.get("function") or tc
                        calls.append(
                            {
                                "id": tc.get("id") or f"call_{len(calls)}",
                                "type": "function",
                                "function": {
                                    "name": fn.get("name", ""),
                                    "arguments": fn.get("arguments")
                                    if isinstance(fn.get("arguments"), str)
                                    else json.dumps(fn.get("arguments") or {}),
                                },
                            }
                        )
        return "".join(text), calls

    async def embed(self, model_id: str, texts: list[str]) -> list[list[float]]:
        vectors = []
        async with httpx.AsyncClient(timeout=_timeout(self.cfg)) as client:
            for t in texts:
                resp = await client.post(
                    f"{self.base}/api/embed",
                    json={"model": model_id, "input": t},
                )
                resp.raise_for_status()
                data = resp.json()
                vectors.append((data.get("embeddings") or [data.get("embedding")])[0])
        return vectors


class FakeAdapter:
    """In-process adapter for tests. `script` maps model id → str | list | callable."""

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
