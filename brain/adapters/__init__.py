"""LLM provider adapters. Registry selects by YAML kind."""

from brain.adapters.anthropic import AnthropicAdapter
from brain.adapters.fake import FakeAdapter
from brain.adapters.gemini import GeminiAdapter
from brain.adapters.groq import GroqAdapter
from brain.adapters.ollama import OllamaAdapter
from brain.adapters.openai import OpenAICompat

__all__ = [
    "AnthropicAdapter",
    "FakeAdapter",
    "GeminiAdapter",
    "GroqAdapter",
    "OllamaAdapter",
    "OpenAICompat",
]
