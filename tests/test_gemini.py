"""Tests for Google Gemini inference adapter and Registry integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from brain.gemini import GeminiAdapter, DEFAULT_GEMINI_BASE, DEFAULT_GEMINI_KEY_ENV
from brain.registry import Registry
from boot import collect_secrets
from ui.dialogs import show_provider_dialog

ROOT = Path(__file__).resolve().parents[1]


def test_gemini_adapter_defaults():
    adapter = GeminiAdapter({})
    assert adapter.base == DEFAULT_GEMINI_BASE
    assert adapter.cfg["api_key_env"] == DEFAULT_GEMINI_KEY_ENV
    assert hasattr(adapter, "embed")


def test_gemini_adapter_custom_config():
    adapter = GeminiAdapter({
        "base_url": "https://custom.gemini.ai/v1",
        "api_key_env": "CUSTOM_GEMINI_KEY",
    })
    assert adapter.base == "https://custom.gemini.ai/v1"
    assert adapter.cfg["api_key_env"] == "CUSTOM_GEMINI_KEY"


def test_gemini_key_fallback_to_google_key(monkeypatch):
    adapter = GeminiAdapter({})

    # Case 1: Neither key set
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="missing env GEMINI_API_KEY"):
        adapter._get_key()

    # Case 2: Only GOOGLE_API_KEY set
    monkeypatch.setenv("GOOGLE_API_KEY", "google-secret-key")
    assert adapter._get_key() == "google-secret-key"

    # Case 3: Both set -> GEMINI_API_KEY takes precedence
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret-key")
    assert adapter._get_key() == "gemini-secret-key"


def test_registry_resolves_gemini_and_google_adapter():
    for kind in ("gemini", "google"):
        cfg = {
            "default_provider": kind,
            "providers": {
                kind: {
                    "kind": kind,
                    "api_key_env": "GEMINI_API_KEY",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                }
            },
            "roles": {
                "master": "gemini-2.5-flash",
                "fast": "gemini-2.5-flash",
                "embeddings": "gemini-embedding-001",
            },
        }
        registry = Registry(cfg)
        provider, model_id, pcfg = registry.resolve("master")
        assert provider == kind
        assert model_id == "gemini-2.5-flash"
        adapter = registry._adapter(provider, pcfg)
        assert isinstance(adapter, GeminiAdapter)


def test_config_models_yaml_contains_gemini():
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert "gemini" in cfg["providers"]
    gemini_cfg = cfg["providers"]["gemini"]
    assert gemini_cfg["api_key_env"] == "GEMINI_API_KEY"
    assert gemini_cfg["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert gemini_cfg["timeout_seconds"] > 0


def test_collect_secrets_includes_gemini_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini_secret_value_123")
    monkeypatch.setenv("GOOGLE_API_KEY", "google_secret_value_456")
    secrets = collect_secrets({})
    assert "gemini_secret_value_123" in secrets
    assert "google_secret_value_456" in secrets


@pytest.mark.asyncio
async def test_gemini_chat_mocked_streaming(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")
    adapter = GeminiAdapter({})

    chunks = [
        b'data: {"choices": [{"delta": {"reasoning": "Analyzing problem..."}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "Gemini "}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "response!"}}]}\n\n',
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
            "gemini-2.5-flash",
            [{"role": "user", "content": "Hello"}],
            on_token=tokens.append,
        )

    assert text == "Gemini response!"
    assert calls == []
    assert "<think>" in tokens
    assert "Analyzing problem..." in tokens
    assert "</think>" in tokens
    assert "Gemini " in tokens
    assert "response!" in tokens


@pytest.mark.asyncio
async def test_gemini_chat_mocked_tool_calling(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")
    adapter = GeminiAdapter({})

    chunks = [
        b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_gemini_1", "type": "function", "function": {"name": "browser", "arguments": "{\\"action\\": "}}]}}]}\n\n',
        b'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\\"open\\", \\"url\\": \\"https://google.com\\"}"}}]}}]}\n\n',
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
            "gemini-2.5-flash",
            [{"role": "user", "content": "Open google.com"}],
            tools=[{"type": "function", "function": {"name": "browser"}}],
        )

    assert text == ""
    assert len(calls) == 1
    assert calls[0]["id"] == "call_gemini_1"
    assert calls[0]["function"]["name"] == "browser"
    assert json.loads(calls[0]["function"]["arguments"]) == {"action": "open", "url": "https://google.com"}


@pytest.mark.asyncio
async def test_gemini_embed_mocked(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")
    adapter = GeminiAdapter({})

    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            {"index": 1, "embedding": [0.4, 0.5, 0.6]},
        ]
    }

    with patch("httpx.AsyncClient.post", return_value=mock_resp):
        vectors = await adapter.embed("gemini-embedding-001", ["first text", "second text"])

    assert len(vectors) == 2
    assert vectors[0] == [0.1, 0.2, 0.3]
    assert vectors[1] == [0.4, 0.5, 0.6]


def test_ui_provider_dialog_displays_gemini():
    models_cfg = {
        "default_provider": "gemini",
        "providers": {
            "openrouter": {"kind": "openrouter", "api_key_env": "OPENROUTER_API_KEY"},
            "groq": {"kind": "groq", "api_key_env": "GROQ_API_KEY"},
            "gemini": {"kind": "gemini", "api_key_env": "GEMINI_API_KEY"},
        },
    }
    show_provider_dialog(models_cfg)
