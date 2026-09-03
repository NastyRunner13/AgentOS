"""Groq inference adapter (OpenAI-compatible chat completions)."""

from __future__ import annotations

from brain.adapters.compat import OnToken
from brain.adapters.openai import OpenAICompat

DEFAULT_GROQ_BASE = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_KEY_ENV = "GROQ_API_KEY"


class GroqAdapter:
    """Adapter for Groq cloud inference.

    Groq provides high-throughput LPU inference using an OpenAI-compatible
    API for chat completions and tool calls, but does not provide an
    /embeddings endpoint.
    """

    def __init__(self, cfg: dict) -> None:
        merged = dict(cfg)
        merged.setdefault("base_url", DEFAULT_GROQ_BASE)
        merged.setdefault("api_key_env", DEFAULT_GROQ_KEY_ENV)
        self.cfg = merged
        self.base = str(merged.get("base_url", DEFAULT_GROQ_BASE)).rstrip("/")
        self._compat = OpenAICompat(merged)

    async def chat(
        self,
        model_id: str,
        messages: list[dict],
        tools=None,
        on_token: OnToken = None,
    ) -> tuple[str, list[dict]]:
        """Stream chat completions via Groq's OpenAI-compatible endpoint."""
        return await self._compat.chat(model_id, messages, tools, on_token)
