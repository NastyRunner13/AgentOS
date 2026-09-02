"""Model registry. Roles resolve through YAML; adapters speak one chat() shape."""

from __future__ import annotations

from brain.anthropic import AnthropicAdapter
from brain.compat import OnToken
from brain.fake import FakeAdapter
from brain.groq import GroqAdapter
from brain.ollama import OllamaAdapter
from brain.openai_compat import OpenAICompat


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
        if kind == "groq":
            return GroqAdapter(pcfg)
        if kind == "anthropic":
            return AnthropicAdapter(pcfg)
        if kind == "ollama":
            return OllamaAdapter(pcfg)
        if kind == "fake":
            return FakeAdapter(pcfg)
        raise KeyError(f"no adapter for provider {provider!r}")
