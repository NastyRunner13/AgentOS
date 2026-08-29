"""Ollama local chat/embeddings adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from brain.compat import OnToken, _timeout


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
