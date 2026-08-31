"""Master: scrub, clarify, fact inject, kb tools, caps."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

import pytest

from brain.registry import FakeAdapter, Registry
from kernel import Task
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


async def test_followup_after_unclear_skips_scorer(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": [
                    '{"clarity":"unclear","questions":["which folder?"]}',
                    '{"clarity":"unclear","questions":["still lost?"]}',
                ],
                "master-a": "listed",
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    first = await master.turn("put it there")
    assert "which folder?" in first
    second = await master.turn("Downloads")
    assert second == "listed"
    assert sum(1 for c in fake.calls if c[0] == "fast-a") == 1
    master_msgs = next(c[1] for c in fake.calls if c[0] == "master-a")
    blob = " ".join(m["content"] for m in master_msgs)
    assert "which folder?" in blob
    assert "Downloads" in blob


async def test_clarify_receives_session_history(tmp_path: Path):
    payloads: list[list[dict]] = []

    def score(messages, tools):
        payloads.append(messages)
        return '{"clarity":"clear"}'

    fake = FakeAdapter({"script": {"fast-a": score, "master-a": "ok"}})
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("hello")
    await master.turn("now list files")
    assert len(payloads) == 2
    second = payloads[1]
    assert second[0]["role"] == "system"
    contents = [m["content"] for m in second]
    assert "hello" in contents
    assert "ok" in contents
    assert second[-1]["content"] == "now list files"


async def test_task_unclear_does_not_skip_foreground_clarify(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": [
                    '{"clarity":"clear"}',
                    '{"clarity":"unclear","questions":["which task folder?"]}',
                    '{"clarity":"unclear","questions":["which cli folder?"]}',
                ],
                "master-a": "hello-ok",
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("hello")
    reply = await master.turn("put it there", task=Task("t1", "bg"))
    assert "which task folder?" in reply
    task_clarify = next(c[1] for c in fake.calls if c[0] == "fast-a" and c[1][-1]["content"] == "put it there")
    assert [m["content"] for m in task_clarify if m["role"] != "system"] == ["put it there"]
    cli = await master.turn("put it there")
    assert "which cli folder?" in cli
    assert sum(1 for c in fake.calls if c[0] == "master-a") == 1


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


async def test_skill_tool_returns_body(tmp_path: Path):
    from brain.skills import Skill

    skill = Skill(name="commit", description="c", path=tmp_path, content="Write a commit.")
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "s1",
                                "type": "function",
                                "function": {"name": "skill", "arguments": '{"name":"commit"}'},
                            }
                        ],
                    ),
                    ("ok", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.skills = [skill]
    await master.turn("commit this")
    tool = next(e for e in memory.latest(20) if e["kind"] == "tool")
    assert "Write a commit." in tool["content"]


async def test_skill_tool_unknown_is_error_string(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "s1",
                                "type": "function",
                                "function": {"name": "skill", "arguments": '{"name":"nope"}'},
                            }
                        ],
                    ),
                    ("ok", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("use nope")
    tool = next(e for e in memory.latest(20) if e["kind"] == "tool")
    assert "unknown skill nope" in tool["content"]


async def test_allowed_tools_blocks_shell(tmp_path: Path):
    from brain.skills import Skill

    ran = []

    async def runner(command, timeout, cwd):
        ran.append(command)
        return "ok"

    skill = Skill(
        name="commit",
        description="c",
        path=tmp_path,
        content="use files only",
        allowed_tools=["files"],
    )
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "s1",
                                "type": "function",
                                "function": {"name": "skill", "arguments": '{"name":"commit"}'},
                            }
                        ],
                    ),
                    (
                        "",
                        [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command":"echo hi"}',
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
    master.skills = [skill]
    await master.turn("commit")
    assert ran == []
    tools = [e for e in memory.latest(20) if e["kind"] == "tool"]
    assert any("skill forbids this tool" in e["content"] for e in tools)


async def test_web_search_not_browser(tmp_path: Path, monkeypatch):
    import tools.web as webmod

    browser_called = []

    async def fake_search(query, perm_cfg, clip=None, **opts):
        return '<untrusted source="web">\n[{"n":1,"title":"X","url":"https://example.com/x","domain":"example.com","snippet":"about x"}]\n</untrusted>'

    async def fake_fetch(url, perm_cfg, clip=None, **opts):
        return f'<untrusted source="web" url="{url}">\nExample Domain about x.\n</untrusted>'

    monkeypatch.setattr(webmod, "search", fake_search)
    monkeypatch.setattr(webmod, "fetch", fake_fetch)

    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            {
                                "id": "w1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query":"X"}',
                                },
                            }
                        ],
                    ),
                    (
                        "",
                        [
                            {
                                "id": "w2",
                                "type": "function",
                                "function": {
                                    "name": "web_fetch",
                                    "arguments": '{"url":"https://example.com/x"}',
                                },
                            }
                        ],
                    ),
                    ("X is described at https://example.com/x", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)

    async def boom(args):
        browser_called.append(args)
        return "browser should not run"

    master.tools.browser = boom
    reply = await master.turn("what is X (web)")
    names = [e["role"] for e in memory.latest(40) if e["kind"] == "tool"]
    assert "web_search" in names
    assert "web_fetch" in names
    assert "browser" not in names
    assert browser_called == []
    assert "<untrusted" in next(e["content"] for e in memory.latest(40) if e["role"] == "web_search")
    assert "https://example.com/x" in reply


def test_registry_unknown_role():
    fake = FakeAdapter({})
    registry = Registry(_models(), extra={"fake": fake})
    with pytest.raises(KeyError):
        registry.resolve("librarian")


def test_openrouter_roles_and_memory_stage():
    models = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    mem = yaml.safe_load((ROOT / "config" / "memory.yaml").read_text(encoding="utf-8"))
    assert "librarian" in (models.get("prompts") or {})
    clarify = models["prompts"]["clarify"]
    assert "files" in clarify
    assert "shell" in clarify
    assert "web_search" in clarify
    assert "web_fetch" in clarify
    assert "skill" in clarify
    assert "working directory" in clarify
    master = models["prompts"]["master"]
    for token in ("web_search", "files", "browser", "computer", "skill"):
        assert token in master
    assert "succeeded" in master
    assert "blocked" in master
    assert "pattern=" in master
    assert mem["stage"] in (0, 1)
    assert mem["stage"] < 2
