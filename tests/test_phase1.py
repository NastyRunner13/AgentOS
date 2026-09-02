"""Phase 1 done-conditions from AGENTARCH.md."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from brain.master import Master
from brain.registry import FakeAdapter, Registry
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tools import NativeTools

ROOT = Path(__file__).resolve().parents[1]


def _models(master_id="master-a", fast_id="fast-a"):
    return {
        "default_provider": "fake",
        "providers": {"fake": {"kind": "fake"}},
        "roles": {
            "master": master_id,
            "fast": fast_id,
            "vision": master_id,
            "embeddings": master_id,
        },
        "prompts": {"master": "You are Friday.", "clarify": "JSON only."},
    }


def _stack(tmp_path: Path, fake: FakeAdapter, perm=None, shell_runner=None):
    models_cfg = _models()
    perm = perm or yaml.safe_load((ROOT / "config" / "permissions.yaml").read_text(encoding="utf-8"))
    bus = Bus()
    gate = Gate(perm, bus)
    tasks = TaskManager(bus, concurrent_slots=4)
    registry = Registry(models_cfg, extra={"fake": fake})
    memory = Episodic(tmp_path / "events.db")
    tools = NativeTools(tmp_path, perm, shell_runner=shell_runner)
    master = Master(
        registry,
        gate,
        tasks,
        memory,
        tools,
        bus,
        system_prompt="You are Friday.",
        clarify_prompt='Reply JSON {"clarity":"clear","questions":[],"assumption":""}',
        clarify=True,
        max_tool_steps=8,
    )
    return bus, gate, tasks, registry, memory, master


async def test_a_chat_roundtrip_streams(tmp_path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": "Hello from the registry",
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    chunks = []
    reply = await master.turn("hi", on_token=chunks.append)
    assert reply == "Hello from the registry"
    assert "".join(chunks) == reply
    assert len(chunks) > 1
    assert fake.calls[0][0] == "fast-a"
    assert any(c[0] == "master-a" for c in fake.calls)


async def test_b_two_tasks_steer_routed():
    bus = Bus()
    tm = TaskManager(bus, concurrent_slots=4)
    received: dict[str, list[str]] = {}

    async def worker(task):
        got = []
        received[task.id] = got
        while True:
            msg = await task.inbox.get()
            if msg == "stop":
                break
            got.append(msg)

    t1 = tm.spawn("one", worker)
    t2 = tm.spawn("two", worker)
    await asyncio.sleep(0)
    await tm.steer(t1.id, "alpha")
    await tm.steer(t2.id, "beta")
    await tm.steer(t1.id, "alpha-2")
    await asyncio.sleep(0.05)
    await t1.inbox.put("stop")
    await t2.inbox.put("stop")
    await asyncio.sleep(0.05)
    assert received[t1.id] == ["alpha", "alpha-2"]
    assert received[t2.id] == ["beta"]


async def test_b_master_applies_steer_to_the_right_task(tmp_path):
    started = asyncio.Event()
    released = asyncio.Event()
    dummy_got: list[str] = []

    async def first(messages, tools):
        started.set()
        await released.wait()
        return "working", []

    def second(messages, tools):
        last = messages[-1]["content"]
        return f"got {last}", []

    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [first, second],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)

    async def master_factory(task):
        await master.turn("start work", task=task)

    async def dummy(task):
        while True:
            msg = await task.inbox.get()
            if msg == "stop":
                break
            dummy_got.append(msg)

    t1 = tasks.spawn("t1", master_factory)
    t2 = tasks.spawn("t2", dummy)
    await asyncio.wait_for(started.wait(), 2)
    await tasks.steer(t1.id, "use chrome")
    await tasks.steer(t2.id, "other")
    released.set()
    for _ in range(50):
        if t1.status in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    await t2.inbox.put("stop")
    assert t1.status == "done"
    assert dummy_got == ["other"]
    steered = [e for e in memory.latest(50) if e["kind"] == "steer"]
    assert any(e["content"] == "use chrome" and e["meta"].get("task_id") == t1.id for e in steered)
    assert not any(e["content"] == "other" and e["meta"].get("task_id") == t1.id for e in steered)


async def test_c_ring2_shell_blocks_until_approved(tmp_path):
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
                    ("ran after approval", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake, shell_runner=runner)
    cards = bus.subscribe("approval.request")
    turn = asyncio.create_task(master.turn("pwn"))
    card = await asyncio.wait_for(cards.get(), 2)
    assert card["ring"] == 2
    assert "Write-Host pwned" in card["action_preview"]
    await asyncio.sleep(0.05)
    assert ran == []
    assert gate.resolve(card["id"], True)
    reply = await asyncio.wait_for(turn, 2)
    assert ran == ["Write-Host pwned"]
    assert "ran after approval" in reply


async def test_c_ring2_denied_does_not_execute(tmp_path):
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
                    ("denied path", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake, shell_runner=runner)
    cards = bus.subscribe("approval.request")
    turn = asyncio.create_task(master.turn("pwn"))
    card = await asyncio.wait_for(cards.get(), 2)
    gate.resolve(card["id"], False)
    await asyncio.wait_for(turn, 2)
    assert ran == []


async def test_d_every_turn_writes_episodic_row(tmp_path):
    fake = FakeAdapter({"script": {"fast-a": '{"clarity":"clear"}', "master-a": "noted"}})
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    assert memory.count() == 0
    await master.turn("remember this")
    assert memory.count() >= 1
    kinds = {e["kind"] for e in memory.latest(20)}
    assert "turn" in kinds


async def test_e_swapping_roles_master_changes_model(tmp_path):
    fake = FakeAdapter({"script": {"model-a": "from A", "model-b": "from B"}})
    cfg = _models("model-a", "fast-a")
    cfg["roles"]["fast"] = "fast-a"
    fake.script["fast-a"] = '{"clarity":"clear"}'
    registry = Registry(cfg, extra={"fake": fake})
    text, _ = await registry.complete("master", [{"role": "user", "content": "x"}])
    assert text == "from A"
    assert fake.calls[-1][0] == "model-a"
    cfg["roles"]["master"] = "model-b"
    text, _ = await registry.complete("master", [{"role": "user", "content": "x"}])
    assert text == "from B"
    assert fake.calls[-1][0] == "model-b"


def test_openrouter_is_default_provider():
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert cfg["default_provider"] in cfg["providers"]
    assert "openrouter" in cfg["providers"]
    assert cfg["providers"]["openrouter"]["api_key_env"] == "OPENROUTER_API_KEY"
    for role in ("master", "fast", "vision", "embeddings"):
        assert role in cfg["roles"]
