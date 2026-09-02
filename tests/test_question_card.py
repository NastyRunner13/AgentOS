"""Tests for interactive multiple-choice question cards and ask_user tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock
from io import StringIO

import pytest
import yaml
from rich.console import Console

from brain.master import Master
from brain.registry import FakeAdapter, Registry
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tests.test_phase1 import _stack
from tools import NativeTools
from ui.renderer import render_card, render_question_card

ROOT = Path(__file__).resolve().parents[1]


def test_render_question_card_output():
    buf = StringIO()
    test_console = Console(file=buf, width=80, color_system=None)
    ev = {
        "id": "q123",
        "kind": "question",
        "question": "Which database would you prefer?",
        "options": ["SQLite (local)", "PostgreSQL", "In-memory"],
        "allow_custom": True,
    }
    render_question_card(ev, out=test_console)
    output = buf.getvalue()
    assert "Clarification needed" in output
    assert "Which database would you prefer?" in output
    assert "(1)" in output
    assert "SQLite (local)" in output
    assert "(2)" in output
    assert "PostgreSQL" in output
    assert "(3)" in output
    assert "In-memory" in output
    assert "(c)" in output
    assert "Custom write-in" in output


def test_render_card_dispatches_question():
    buf = StringIO()
    test_console = Console(file=buf, width=80, color_system=None)
    ev = {
        "id": "q456",
        "kind": "question",
        "question": "Choose an architecture style",
        "options": ["Monolith", "Microservices"],
    }
    render_card(ev, out=test_console)
    output = buf.getvalue()
    assert "Clarification needed" in output
    assert "Choose an architecture style" in output
    assert "Monolith" in output
    assert "Microservices" in output


async def test_clarify_triggers_question_card_and_continues(tmp_path: Path):
    """Pre-implementation clarify raises question card and continues turn inline."""
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": (
                    '{"clarity":"unclear","question":"Which database driver?",'
                    '"options":["SQLite","Postgres"]}'
                ),
                "master-a": "I have configured the database with SQLite.",
            }
        }
    )
    bus, gate, tasks, adapter, memory, master = _stack(tmp_path, fake)

    cards = bus.subscribe("approval.request")

    async def auto_resolve():
        card = await asyncio.wait_for(cards.get(), 2)
        assert card["kind"] == "question"
        assert card["question"] == "Which database driver?"
        assert card["options"] == ["SQLite", "Postgres"]
        gate.resolve(card["id"], "SQLite")

    resolver_task = asyncio.create_task(auto_resolve())
    reply = await master.turn("Set up the database")
    await resolver_task

    assert "configured the database with SQLite" in reply
    # Verify the user turn in master history carried the resolved clarification
    master_calls = [c for c in fake.calls if c[0] == "master-a"]
    assert len(master_calls) == 1
    messages = master_calls[0][1]
    last_user = next(m["content"] for m in reversed(messages) if m["role"] == "user")
    assert "[clarification: Which database driver? -> SQLite]" in last_user


async def test_clarify_without_options_falls_back_to_text_questions(tmp_path: Path):
    """If clarify returns unclear without options, falls back to text reply."""
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"unclear","questions":["What directory?"]}',
                "master-a": "not called",
            }
        }
    )
    bus, gate, tasks, adapter, memory, master = _stack(tmp_path, fake)

    cards = bus.subscribe("approval.request")
    reply = await master.turn("save this")

    assert "I need a bit more:" in reply
    assert "What directory?" in reply
    assert cards.empty()


async def test_ask_user_tool_in_master_loop(tmp_path: Path):
    """The agent can call ask_user tool during execution to ask multiple choices."""
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    # Turn 1: Master calls ask_user
                    (
                        "Let me ask the user about the UI framework.",
                        [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "ask_user",
                                    "arguments": '{"question":"Which frontend framework?","options":["React","Vanilla JS"]}',
                                },
                            }
                        ],
                    ),
                    # Turn 2: Master receives tool response and finishes
                    "Proceeding with React implementation.",
                ],
            }
        }
    )
    bus, gate, tasks, adapter, memory, master = _stack(tmp_path, fake)

    cards = bus.subscribe("approval.request")

    async def auto_resolve():
        card = await asyncio.wait_for(cards.get(), 2)
        assert card["kind"] == "question"
        assert card["question"] == "Which frontend framework?"
        assert card["options"] == ["React", "Vanilla JS"]
        gate.resolve(card["id"], "React")

    resolver_task = asyncio.create_task(auto_resolve())
    reply = await master.turn("Create the frontend app")
    await resolver_task

    assert "Proceeding with React implementation" in reply
    # Verify tool results in memory
    tool_rows = memory.latest(10)
    assert any(r.get("role") == "ask_user" and "React" in r.get("content", "") for r in tool_rows)
