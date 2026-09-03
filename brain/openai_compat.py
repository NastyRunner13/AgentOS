"""OpenAI-compat re-export. Implementation lives in brain/adapters/openai.py."""

from brain.adapters.openai import OpenAICompat, wire_messages, _consume_openai_sse

__all__ = ["OpenAICompat", "wire_messages", "_consume_openai_sse"]
