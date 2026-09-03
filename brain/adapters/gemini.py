"""Google Gemini inference adapter (OpenAI-compatible chat and embeddings)."""

from __future__ import annotations

import os

from brain.adapters.compat import OnToken
from brain.adapters.openai import OpenAICompat

DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_GEMINI_KEY_ENV = "GEMINI_API_KEY"


class GeminiAdapter(OpenAICompat):
    """Adapter for Google Gemini cloud models.

    Uses Google's official OpenAI-compatible endpoint for chat completions,
    streaming, tool calling, and embeddings (e.g. gemini-embedding-001).
    Supports either GEMINI_API_KEY or GOOGLE_API_KEY.
    """

    def __init__(self, cfg: dict) -> None:
        merged = dict(cfg)
        merged.setdefault("base_url", DEFAULT_GEMINI_BASE)
        merged.setdefault("api_key_env", DEFAULT_GEMINI_KEY_ENV)
        super().__init__(merged)

    def _get_key(self) -> str | None:
        env = self.cfg.get("api_key_env", DEFAULT_GEMINI_KEY_ENV)
        key = os.environ.get(env) if env else None
        if not key and env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            alt = "GOOGLE_API_KEY" if env == "GEMINI_API_KEY" else "GEMINI_API_KEY"
            key = os.environ.get(alt)
        if not key and env:
            raise RuntimeError(f"missing env {env} (or GOOGLE_API_KEY) — set it in .env")
        return key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json", **(self.cfg.get("headers") or {})}
        key = self._get_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def chat(
        self,
        model_id: str,
        messages: list[dict],
        tools=None,
        on_token: OnToken = None,
    ) -> tuple[str, list[dict]]:
        return await super().chat(model_id, messages, tools, on_token)

