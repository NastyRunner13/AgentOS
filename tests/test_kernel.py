"""Kernel invariants: bus, tasks, rings, cards."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from kernel import Bus, Gate, TaskManager
from tools import SPECS

ROOT = Path(__file__).resolve().parents[1]


def _perm(**overrides) -> dict:
    cfg = yaml.safe_load((ROOT / "config" / "permissions.yaml").read_text(encoding="utf-8"))
    cfg.update(overrides)
    return cfg


def test_bus_publish_reaches_subscribers():
    bus = Bus()
    a = bus.subscribe("tool.call")
    b = bus.subscribe("tool.call")
    bus.publish("tool.call", {"name": "shell"})
    assert a.get_nowait()["name"] == "shell"
    assert b.get_nowait()["topic"] == "tool.call"


def test_bus_unsubscribe_stops_delivery():
    bus = Bus()
    q = bus.subscribe("error")
    bus.unsubscribe("error", q)
    bus.publish("error", {"error": "x"})
    assert q.empty()


async def test_task_slots_cap_concurrency():
    tm = TaskManager(Bus(), concurrent_slots=1)
    started: list[str] = []
    release = asyncio.Event()

    async def worker(task):
        started.append(task.id)
        await release.wait()

    t1 = tm.spawn("one", worker)
    t2 = tm.spawn("two", worker)
    await asyncio.sleep(0.05)
    assert started == [t1.id]
    assert t2.status == "queued"
    release.set()
    for _ in range(40):
        if t2.id in started:
            break
        await asyncio.sleep(0.02)
    assert t2.id in started


async def test_steer_unknown_and_done():
    tm = TaskManager(Bus(), concurrent_slots=2)

    async def worker(task):
        return

    t = tm.spawn("done-soon", worker)
    with pytest.raises(KeyError):
        await tm.steer("nope", "x")
    for _ in range(40):
        if t.status in ("done", "failed"):
            break
        await asyncio.sleep(0.02)
    with pytest.raises(ValueError):
        await tm.steer(t.id, "late")


async def test_failed_factory_marks_failed():
    tm = TaskManager(Bus(), concurrent_slots=1)

    async def boom(task):
        raise RuntimeError("nope")

    t = tm.spawn("boom", boom)
    for _ in range(40):
        if t.status == "failed":
            break
        await asyncio.sleep(0.02)
    assert t.status == "failed"
    assert "nope" in (t.error or "")


def test_every_spec_has_explicit_ring():
    perm = _perm()
    gate = Gate(perm, Bus())
    names = {spec["function"]["name"] for spec in SPECS}
    expected = {
        "shell": 1,
        "files": 0,
        "browser": 1,
        "computer": 1,
        "web_search": 0,
        "web_fetch": 0,
        "skill": 0,
        "spawn_task": 0,
        "kb_read": 0,
        "kb_propose": 1,
        "kb_consolidate": 1,
    }
    assert names == set(expected), names
    args = {
        "action": "read",
        "path": ".",
        "command": "echo hi",
        "query": "x",
        "kind": "fact",
        "url": "https://example.com",
        "name": "x",
    }
    for name, ring in expected.items():
        assert gate.classify(name, args) == ring, name


def test_unknown_tool_is_ring_2():
    gate = Gate(_perm(), Bus())
    assert gate.classify("not_a_tool", {}) == 2


def test_shell_allowlist_and_other():
    gate = Gate(_perm(), Bus())
    assert gate.classify("shell", {"command": "echo hi"}) == 1
    assert gate.classify("shell", {"command": "Get-Date"}) == 1
    assert gate.classify("shell", {"command": "Write-Host pwned"}) == 2


def test_files_rings_and_delete_threshold():
    gate = Gate(_perm(), Bus())
    assert gate.classify("files", {"action": "search", "path": "."}) == 0
    assert gate.classify("files", {"action": "write", "path": "a.txt"}) == 1
    assert gate.classify("files", {"action": "delete", "path": "a.txt", "_size": 1}) == 2
    assert gate.classify("files", {"action": "delete", "path": "a.txt", "_size": 2_000_000}) == 3


def test_gate_preview():
    gate = Gate(_perm(), Bus())
    assert "pwned" in gate.preview("shell", {"command": "pwned"})
    assert "kb_propose" in gate.preview("kb_propose", {"statement": "Standup at 9"})


async def test_card_expiry_denies():
    gate = Gate(_perm(**{"card": {"expiry_seconds": 0, "expire_action": "deny"}}), Bus())
    cards = gate.bus.subscribe("approval.request")
    allowed = await gate.check("shell", {"command": "Write-Host pwned"})
    assert allowed is False
    card = cards.get_nowait()
    assert card["ring"] == 2
    assert gate.resolve(card["id"], True) is False


async def test_resolve_unknown_and_double():
    gate = Gate(_perm(), Bus())
    cards = gate.bus.subscribe("approval.request")
    task = asyncio.create_task(gate.check("shell", {"command": "Write-Host pwned"}))
    card = await asyncio.wait_for(cards.get(), 2)
    assert gate.resolve(card["id"], True) is True
    assert gate.resolve(card["id"], True) is False
    assert gate.resolve("missing", True) is False
    assert await asyncio.wait_for(task, 2) is True
