"""Master: scrub, clarify, fact inject, kb tools, caps."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

import pytest

from brain.master import _tool_groups
from brain.registry import FakeAdapter, Registry
from kernel import Bus, Gate, Task
from memory import Episodic
from tests.test_phase1 import _models, _stack

ROOT = Path(__file__).resolve().parents[1]


def _tc(cid: str, name: str, arguments: str) -> dict:
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _classify():
    perm = yaml.safe_load((ROOT / "config" / "permissions.yaml").read_text(encoding="utf-8"))
    return Gate(perm, Bus()).classify


async def test_secrets_never_land_in_episodic(tmp_path: Path):
    fake = FakeAdapter({"script": {"fast-a": '{"clarity":"clear"}', "master-a": "ok"}})
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.secrets = ["s3cr3t-token"]
    await master.turn("my key is s3cr3t-token please remember")
    blob = json.dumps(memory.latest(20))
    assert "s3cr3t-token" not in blob
    assert "***" in blob


async def test_tool_secrets_scrubbed_in_episodic(tmp_path: Path):
    async def fake_runner(cmd, timeout, cwd):
        return "result contains s3cr3t-api-key inside"

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
                                    "arguments": '{"command":"echo s3cr3t-api-key"}',
                                },
                            }
                        ],
                    ),
                    ("finished", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(
        tmp_path, fake, shell_runner=fake_runner
    )
    master.secrets = ["s3cr3t-api-key"]
    await master.turn("run echo")
    events = memory.latest(20)
    blob = json.dumps(events)
    assert "s3cr3t-api-key" not in blob
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


async def test_computer_see_does_not_consume_tool_step(tmp_path: Path):
    see = {
        "id": "s",
        "type": "function",
        "function": {"name": "computer", "arguments": '{"action":"see"}'},
    }
    kb = {
        "id": "k",
        "type": "function",
        "function": {"name": "kb_read", "arguments": '{"query":"x"}'},
    }
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [("", [see]), ("", [see]), ("", [kb]), ("done after see", [])],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.max_tool_steps = 2
    reply = await master.turn("look then recall")
    master_calls = [c for c in fake.calls if c[0] == "master-a"]
    assert len(master_calls) == 4
    assert reply == "done after see"


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


async def test_tool_followup_404_retries_flattened(tmp_path: Path, monkeypatch):
    import tools.web as webmod

    async def fake_search(query, perm_cfg, clip=None, **opts):
        return '<untrusted source="web">\n[{"n":1,"title":"X","url":"https://example.com/x"}]\n</untrusted>'

    monkeypatch.setattr(webmod, "search", fake_search)
    n = {"master": 0}

    def master_script(messages, tools):
        n["master"] += 1
        if n["master"] == 1:
            return (
                "",
                [
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": '{"query":"X"}'},
                    }
                ],
            )
        if tools:
            raise RuntimeError(
                '404 {"error":{"message":"Provider returned error","code":404}}'
            )
        blob = " ".join(str(m.get("content") or "") for m in messages)
        assert "[web_search result]" in blob
        assert "example.com" in blob
        return ("X is described at https://example.com/x", [])

    fake = FakeAdapter(
        {"script": {"fast-a": '{"clarity":"clear"}', "master-a": master_script}}
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    reply = await master.turn("what is X (web)")
    assert "https://example.com/x" in reply
    assert "model error" not in reply
    assert n["master"] == 3
    master_calls = [c for c in fake.calls if c[0] == "master-a"]
    assert len(master_calls) == 3
    tool_msg = next(m for m in master_calls[1][1] if m.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "call_0"
    assert master_calls[2][2] is None


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
    assert "Default is clear" in clarify
    assert "mutually exclusive" in clarify
    assert "Do not ask every turn" in clarify
    master = models["prompts"]["master"]
    for token in ("web_search", "files", "browser", "computer", "skill"):
        assert token in master
    assert "Do not ask every turn" in master
    assert "ask_user only when a fork blocks the turn" in master
    assert "Independent reads" in master
    architect = models["prompts"]["architect"]
    assert "plan.md" in architect
    assert "Do not implement" in architect
    assert "succeeded" in master
    assert "blocked" in master
    assert "pattern=" in master
    assert mem["stage"] in (0, 1)
    assert mem["stage"] < 2


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def test_computer_see_attaches_screenshot_image(tmp_path: Path):
    shot = tmp_path / "screen-model.png"
    shot.write_bytes(TINY_PNG)

    class FakeOp:
        async def execute(self, args):
            return json.dumps(
                {
                    "action": "see",
                    "path": "pixels",
                    "verified": True,
                    "verify": {"ok": True, "detail": "screen observed"},
                    "screenshot": str(shot),
                    "image_size": [1, 1],
                    "observation": '<untrusted source="screen_vision">desk</untrusted>',
                }
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
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "computer", "arguments": '{"action":"see"}'},
                            }
                        ],
                    ),
                    ("I see the desk.", []),
                ],
            }
        }
    )
    _bus, _gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    master.tools.operator = FakeOp()
    reply = await master.turn("look at the screen")
    assert reply == "I see the desk."
    master_calls = [c for c in fake.calls if c[0] == "master-a"]
    assert len(master_calls) >= 2
    blob = json.dumps(master_calls[1][1])
    assert "image_url" in blob
    assert "data:image/png;base64," in blob
    assert "0-1000" in blob


async def test_master_stops_blind_computer_batch_calls(tmp_path: Path):
    class FakeOp:
        def __init__(self):
            self.clicks = []

        async def execute(self, args):
            if args.get("action") == "click":
                self.clicks.append((args.get("x"), args.get("y")))
                return json.dumps({"action": "click", "verified": True, "x": args.get("x"), "y": args.get("y")})
            return json.dumps({"action": "see", "verified": True})

    op = FakeOp()
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
                                "function": {"name": "computer", "arguments": '{"action":"click","x":100,"y":200}'},
                            },
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {"name": "computer", "arguments": '{"action":"click","x":300,"y":400}'},
                            },
                        ],
                    ),
                    ("Done with first click.", []),
                ],
            }
        }
    )
    _bus, _gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    master.tools.operator = op
    reply = await master.turn("click button then click another")
    assert reply == "Done with first click."
    # Only the first click should have executed; the second was blocked from blind execution
    assert op.clicks == [(100, 200)]


def test_tool_groups_reads_together_writes_and_cards_serial():
    classify = _classify()
    reads = [
        _tc("a", "files", '{"action":"read","path":"a.txt"}'),
        _tc("b", "kb_read", '{"query":"x"}'),
        _tc("c", "web_search", '{"query":"x"}'),
    ]
    groups = _tool_groups(reads, classify)
    assert len(groups) == 1
    assert [c["id"] for c in groups[0]] == ["a", "b", "c"]

    same = [
        _tc("w1", "files", '{"action":"write","path":"x.txt","content":"1"}'),
        _tc("w2", "files", '{"action":"write","path":"x.txt","content":"2"}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(same, classify)] == [["w1"], ["w2"]]

    read_then_write = [
        _tc("r", "files", '{"action":"read","path":"x.txt"}'),
        _tc("w", "files", '{"action":"write","path":"x.txt","content":"2"}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(read_then_write, classify)] == [["r"], ["w"]]

    different = [
        _tc("w1", "files", '{"action":"write","path":"a.txt","content":"1"}'),
        _tc("w2", "files", '{"action":"write","path":"b.txt","content":"2"}'),
    ]
    assert len(_tool_groups(different, classify)) == 1

    mixed = [
        _tc("s", "skill", '{"name":"commit"}'),
        _tc("r", "kb_read", '{"query":"x"}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(mixed, classify)] == [["s"], ["r"]]

    browser = [
        _tc("b", "browser", '{"action":"snapshot"}'),
        _tc("f", "web_fetch", '{"url":"https://example.com"}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(browser, classify)] == [["b"], ["f"]]

    card = [
        _tc("sh", "shell", '{"command":"Write-Host pwned"}'),
        _tc("r", "files", '{"action":"read","path":"a.txt"}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(card, classify)] == [["sh"], ["r"]]

    clicks = [
        _tc("c1", "computer", '{"action":"click","x":1,"y":1}'),
        _tc("c2", "computer", '{"action":"click","x":2,"y":2}'),
    ]
    assert [[c["id"] for c in g] for g in _tool_groups(clicks, classify)] == [["c1"], ["c2"]]

    see_and_read = [
        _tc("see", "computer", '{"action":"see"}'),
        _tc("r", "files", '{"action":"read","path":"a.txt"}'),
    ]
    assert len(_tool_groups(see_and_read, classify)) == 1


async def test_independent_ring0_tools_overlap(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            _tc("a", "kb_read", '{"query":"one"}'),
                            _tc("b", "kb_read", '{"query":"two"}'),
                        ],
                    ),
                    ("done", []),
                ],
            }
        }
    )
    _bus, _gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    in_flight = 0
    peak = 0
    orig = master._run_tool

    async def slow(call, task):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        try:
            return await orig(call, task)
        finally:
            in_flight -= 1

    master._run_tool = slow
    reply = await master.turn("recall two facts")
    assert reply == "done"
    assert peak == 2
    master_calls = [c for c in fake.calls if c[0] == "master-a"]
    tool_msgs = [m for m in master_calls[1][1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]


async def test_same_path_writes_stay_serial(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            _tc(
                                "w1",
                                "files",
                                '{"action":"write","path":"x.txt","content":"1"}',
                            ),
                            _tc(
                                "w2",
                                "files",
                                '{"action":"write","path":"x.txt","content":"2"}',
                            ),
                        ],
                    ),
                    ("wrote", []),
                ],
            }
        }
    )
    _bus, _gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    in_flight = 0
    peak = 0
    orig = master._run_tool

    async def slow(call, task):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        try:
            return await orig(call, task)
        finally:
            in_flight -= 1

    master._run_tool = slow
    await master.turn("write twice")
    assert peak == 1
    assert (tmp_path / "x.txt").read_text(encoding="utf-8") == "2"


async def test_ring2_card_not_gathered_with_later_read(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": [
                    (
                        "",
                        [
                            _tc("sh", "shell", '{"command":"Write-Host pwned"}'),
                            _tc("r", "files", '{"action":"read","path":"a.txt"}'),
                        ],
                    ),
                    ("stopped", []),
                ],
            }
        }
    )
    bus, gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    read_started = asyncio.Event()
    orig = master._run_tool

    async def wrap(call, task):
        name = (call.get("function") or {}).get("name")
        if name == "files":
            read_started.set()
        return await orig(call, task)

    master._run_tool = wrap
    turn = asyncio.create_task(master.turn("pwn then read"))
    cards = bus.subscribe("approval.request")
    card = await asyncio.wait_for(cards.get(), 2)
    await asyncio.sleep(0.05)
    assert not read_started.is_set()
    gate.resolve(card["id"], False)
    await asyncio.wait_for(turn, 2)
    assert read_started.is_set()


async def test_skill_runs_before_parallel_reads(tmp_path: Path):
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
                            _tc("r1", "kb_read", '{"query":"one"}'),
                            _tc("s1", "skill", '{"name":"commit"}'),
                            _tc("r2", "kb_read", '{"query":"two"}'),
                        ],
                    ),
                    ("ok", []),
                ],
            }
        }
    )
    _bus, _gate, _tasks, _registry, _memory, master = _stack(tmp_path, fake)
    master.skills = [skill]
    order: list[str] = []
    orig = master._run_tool

    async def wrap(call, task):
        name = (call.get("function") or {}).get("name") or ""
        order.append(name)
        if name == "kb_read":
            await asyncio.sleep(0.02)
        return await orig(call, task)

    master._run_tool = wrap
    await master.turn("load skill and recall")
    assert order[0] == "skill"
    assert order[1:] == ["kb_read", "kb_read"]

