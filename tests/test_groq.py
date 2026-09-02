"""Tests for Groq inference adapter and Registry integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from brain.groq import GroqAdapter, DEFAULT_GROQ_BASE, DEFAULT_GROQ_KEY_ENV
from brain.registry import Registry
from ui.dialogs import show_provider_dialog

ROOT = Path(__file__).resolve().parents[1]


def test_groq_adapter_defaults():
    adapter = GroqAdapter({})
    assert adapter.base == DEFAULT_GROQ_BASE
    assert adapter.cfg["api_key_env"] == DEFAULT_GROQ_KEY_ENV
    assert not hasattr(adapter, "embed")


def test_groq_adapter_custom_config():
    adapter = GroqAdapter({
        "base_url": "https://custom.groq.com/v1",
        "api_key_env": "CUSTOM_GROQ_KEY",
    })
    assert adapter.base == "https://custom.groq.com/v1"
    assert adapter.cfg["api_key_env"] == "CUSTOM_GROQ_KEY"


def test_registry_resolves_groq_adapter():
    cfg = {
        "default_provider": "groq",
        "providers": {
            "groq": {
                "api_key_env": "GROQ_API_KEY",
                "base_url": "https://api.groq.com/openai/v1",
            }
        },
        "roles": {
            "master": "llama-3.3-70b-versatile",
            "fast": "llama-3.1-8b-instant",
        },
    }
    registry = Registry(cfg)
    provider, model_id, pcfg = registry.resolve("master")
    assert provider == "groq"
    assert model_id == "llama-3.3-70b-versatile"
    adapter = registry._adapter(provider, pcfg)
    assert isinstance(adapter, GroqAdapter)


def test_registry_embed_fails_for_groq():
    cfg = {
        "default_provider": "groq",
        "providers": {
            "groq": {
                "api_key_env": "GROQ_API_KEY",
            }
        },
        "roles": {
            "embeddings": "some-groq-model",
        },
    }
    registry = Registry(cfg)
    with pytest.raises(RuntimeError, match="has no embeddings"):
        import asyncio
        asyncio.run(registry.embed(["hello world"]))


def test_config_models_yaml_contains_groq():
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert "groq" in cfg["providers"]
    groq_cfg = cfg["providers"]["groq"]
    assert groq_cfg["api_key_env"] == "GROQ_API_KEY"
    assert groq_cfg["base_url"] == "https://api.groq.com/openai/v1"
    assert groq_cfg["timeout_seconds"] > 0


@pytest.mark.asyncio
async def test_groq_chat_mocked_streaming(monkeypatch):
    monkeypatch.setenv("MOCK_GROQ_KEY", "gsk_test_token")
    adapter = GroqAdapter({"api_key_env": "MOCK_GROQ_KEY"})

    chunks = [
        b'data: {"choices": [{"delta": {"reasoning": "Thinking step 1"}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "Hello "}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "world!"}}]}\n\n',
        b'data: [DONE]\n\n',
    ]

    async def mock_aiter_lines():
        for c in chunks:
            yield c.decode("utf-8")

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_aiter_lines

    tokens: list[str] = []

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp

        text, calls = await adapter.chat(
            "llama-3.3-70b-versatile",
            [{"role": "user", "content": "Hi"}],
            on_token=tokens.append,
        )

    assert text == "Hello world!"
    assert calls == []
    assert "<think>" in tokens
    assert "Thinking step 1" in tokens
    assert "</think>" in tokens
    assert "Hello " in tokens
    assert "world!" in tokens


@pytest.mark.asyncio
async def test_groq_chat_mocked_tool_calling(monkeypatch):
    monkeypatch.setenv("MOCK_GROQ_KEY", "gsk_test_token")
    adapter = GroqAdapter({"api_key_env": "MOCK_GROQ_KEY"})

    chunks = [
        b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_123", "type": "function", "function": {"name": "files", "arguments": "{\\"action\\": "}}]}}]}\n\n',
        b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"read\\", \\"path\\": \\"test.txt\\"}"}}]}}]}\n\n',
        b'data: [DONE]\n\n',
    ]

    async def mock_aiter_lines():
        for c in chunks:
            yield c.decode("utf-8")

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = mock_aiter_lines

    with patch("httpx.AsyncClient.stream") as mock_stream:
        mock_stream.return_value.__aenter__.return_value = mock_resp

        text, calls = await adapter.chat(
            "llama-3.3-70b-versatile",
            [{"role": "user", "content": "Read test.txt"}],
            tools=[{"type": "function", "function": {"name": "files"}}],
        )

    assert text == ""
    assert len(calls) == 1
    assert calls[0]["id"] == "call_123"
    assert calls[0]["function"]["name"] == "files"
    assert json.loads(calls[0]["function"]["arguments"]) == {"action": "read", "path": "test.txt"}


def test_ui_provider_dialog_displays_groq():
    models_cfg = {
        "default_provider": "openrouter",
        "providers": {
            "openrouter": {"kind": "openrouter", "api_key_env": "OPENROUTER_API_KEY"},
            "groq": {"kind": "groq", "api_key_env": "GROQ_API_KEY"},
        },
    }
    show_provider_dialog(models_cfg)
