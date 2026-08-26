"""Master: scrub, clarify, fact inject, kb tools, caps."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

import pytest

from brain.registry import FakeAdapter, Registry
from memory import Episodic
from tests.test_phase1 import _models, _stack

ROOT = Path(__file__).resolve().parents[1]


async def test_secrets_never_land_in_episodic(tmp_path: Path):
    fake = FakeAdapter({"script": {"fast-a": '{"clarity":"clear"}', "master-a": "ok"}})
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.secrets = ["s3cr3t-token"]
    await master.turn("my key is s3cr3t-token please remember")
    blob = json.dumps(memory.latest(20))
    assert "s3cr3t-token" not in blob
    assert "***" in blob


async def test_unclear_asks_and_skips_master(tmp_path: Path):
    fake = FakeAdapter(
        {"script": {"fast-a": '{"clarity":"unclear","questions":["which folder?"]}', "master-a": "should not run"}}
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    reply = await master.turn("put it there")
    assert "which folder?" in reply
    assert all(c[0] != "master-a" for c in fake.calls)


async def test_trivial_assumption_appended(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"trivial","assumption":"Downloads"}',
                "master-a": "saved",
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("save this")
    master_msg = next(c for c in fake.calls if c[0] == "master-a")
    user = next(m["content"] for m in master_msg[1] if m["role"] == "user")
    assert "[assumption] Downloads" in user


async def test_max_tool_steps(tmp_path: Path):
    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "kb_read", "arguments": '{"query":"x"}'},
    }
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [("", [call])] * 5,
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.max_tool_steps = 2
    reply = await master.turn("loop")
    assert "hit max tool steps" in reply or reply == ""


async def test_confirmed_facts_injected_not_l2_chatter(tmp_path: Path):
    fake = FakeAdapter({"script": {"fast-a": '{"clarity":"clear"}', "master-a": "nine"}})
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    pid = memory.propose({"kind": "fact", "statement": "Standup is at 09:00"})
    memory.approve([pid])
    for i in range(8):
        memory.write("turn", content=f"chatter {i} about weather", role="user")
    await master.turn("when is standup?")
    sys_content = next(c[1][0]["content"] for c in fake.calls if c[0] == "master-a")
    assert "Standup is at 09:00" in sys_content
    assert "chatter" not in sys_content
    assert "Confirmed facts" in sys_content


async def test_kb_propose_stays_pending(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "p1",
                                "type": "function",
                                "function": {
                                    "name": "kb_propose",
                                    "arguments": '{"kind":"fact","statement":"Theme is dark"}',
                                },
                            }
                        ],
                    ),
                    ("queued", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("remember dark theme")
    assert memory.valid_facts() == []
    pending = memory.pending()
    assert len(pending) == 1
    assert pending[0]["payload"]["statement"] == "Theme is dark"
    kinds = {e["kind"] for e in memory.latest(20)}
    assert "tool" in kinds


async def test_kb_read_returns_only_confirmed(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "r1",
                                "type": "function",
                                "function": {"name": "kb_read", "arguments": '{"query":"standup"}'},
                            }
                        ],
                    ),
                    ("done", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    memory.propose({"kind": "fact", "statement": "Favorite color is blue"})
    pid = memory.propose({"kind": "fact", "statement": "Standup is at 09:00"})
    memory.approve([pid])
    await master.turn("standup?")
    tool_rows = [e for e in memory.latest(20) if e["kind"] == "tool"]
    assert tool_rows
    payload = json.loads(tool_rows[0]["content"])
    statements = [f["statement"] for f in payload]
    assert "Standup is at 09:00" in statements
    assert all("blue" not in s.lower() for s in statements)


async def test_denied_shell_logged_not_run(tmp_path: Path):
    ran = []

    async def runner(command, timeout, cwd):
        ran.append(command)
        return "ok"

    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command":"Write-Host pwned"}',
                                },
                            }
                        ],
                    ),
                    ("stopped", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake, shell_runner=runner)
    turn = asyncio.create_task(master.turn("pwn"))
    cards = bus.subscribe("approval.request")
    card = await asyncio.wait_for(cards.get(), 2)
    gate.resolve(card["id"], False)
    await asyncio.wait_for(turn, 2)
    assert ran == []
    tool = next(e for e in memory.latest(20) if e["kind"] == "tool")
    assert tool["content"] == "denied"
    assert tool["meta"]["denied"] is True


def test_registry_unknown_role():
    fake = FakeAdapter({})
    registry = Registry(_models(), extra={"fake": fake})
    with pytest.raises(KeyError):
        registry.resolve("librarian")


def test_openrouter_roles_and_memory_stage():
    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    mem = yaml.safe_load((ROOT / "config" / "memory.yaml").read_text(encoding="utf-8"))
    assert "librarian" in (models.get("prompts") or {})
    assert mem["stage"] in (0, 1)
    assert mem["stage"] < 2
