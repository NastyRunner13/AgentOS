"""Architect plan store, gate, and composer actions."""

from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path

from rich.console import Console

from brain.registry import FakeAdapter
from tests.test_phase1 import _stack
from tools.files import is_plan_path
from ui.plans import (
    PLAN_APPROVE,
    PLAN_QUIT,
    PlanStore,
    execute_prompt,
    plan_action,
    revise_prompt,
    title_from_body,
    updated_plan_body,
)
from ui.renderer import render_plan, render_plans


def test_is_plan_path_only_workspace_root(tmp_path: Path):
    assert is_plan_path("plan.md", tmp_path) is True
    assert is_plan_path("./plan.md", tmp_path) is True
    assert is_plan_path(str(tmp_path / "plan.md"), tmp_path) is True
    assert is_plan_path("src/plan.md", tmp_path) is False
    assert is_plan_path("hello.py", tmp_path) is False
    assert is_plan_path("", tmp_path) is False


def test_plan_store_upsert_waiting_and_history(tmp_path: Path):
    store = PlanStore(tmp_path / "plans")
    first = store.upsert_waiting("sess1", "# Touch planned.txt\n\nCreate the file.")
    assert first.status == "waiting_approval"
    assert first.title == "Touch planned.txt"
    again = store.upsert_waiting("sess1", "# Touch planned.txt\n\nRevised.")
    assert again.id == first.id
    assert "Revised" in again.body
    approved = store.set_status(first.id, "approved")
    assert approved.status == "approved"
    second = store.upsert_waiting("sess1", "# Next job")
    assert second.id != first.id
    rows = store.list(session_id="sess1")
    assert len(rows) == 2
    assert store.get(first.id).status == "approved"
    discarded = store.set_status(second.id, "discarded")
    assert discarded.status == "discarded"
    assert store.waiting_for("sess1") is None
    assert store.latest_for("sess1").id == second.id


def test_plan_action_keys_and_typed_comment():
    assert plan_action("hello", waiting=False) == ("none", "hello")
    assert plan_action("a", waiting=True) == ("approve", "")
    assert plan_action(PLAN_APPROVE, waiting=True) == ("approve", "")
    assert plan_action("q", waiting=True) == ("quit", "")
    assert plan_action(PLAN_QUIT, waiting=True) == ("quit", "")
    assert plan_action("s", waiting=True) == ("ask_changes", "")
    assert plan_action("c", waiting=True) == ("ask_comment", "")
    assert plan_action("add tests", waiting=True) == ("comment", "add tests")
    assert plan_action("more steps", waiting=True, collecting="changes") == (
        "changes",
        "more steps",
    )


def test_execute_and_revise_prompts():
    from ui.plans import Plan

    plan = Plan(id="p1", title="T", status="approved", session_id="s", body="1. Write x")
    text = execute_prompt(plan)
    assert "1. Write x" in text
    assert "Execute the approved plan" in text
    rev = revise_prompt("skip tests", "changes")
    assert "Change request" in rev
    assert "skip tests" in rev
    assert "Do not implement" in rev


def test_title_from_body():
    assert title_from_body("# Hello\n\nBody") == "Hello"
    assert title_from_body("") == "untitled plan"


def test_render_waiting_plan_shows_actions():
    buf = StringIO()
    c = Console(file=buf, force_terminal=False, color_system=None, width=80, legacy_windows=False)
    render_plan("plan.md", ["# Touch planned.txt", "", "Create it."], status="waiting_approval", out=c)
    out = buf.getvalue()
    assert "Touch planned.txt" in out
    assert "approve" in out.lower()
    assert "Waiting on plan approval" in out

    buf2 = StringIO()
    c2 = Console(file=buf2, force_terminal=False, color_system=None, width=80, legacy_windows=False)
    render_plan("plan.md", ["# Done"], status="approved", out=c2)
    assert "Plan approved" in buf2.getvalue()
    assert "Waiting on plan approval" not in buf2.getvalue()

    buf3 = StringIO()
    c3 = Console(file=buf3, force_terminal=False, color_system=None, width=80, legacy_windows=False)
    render_plans([], out=c3)
    assert "No saved plans" in buf3.getvalue()


def test_updated_plan_body_only_on_architect_change(tmp_path: Path):
    path = tmp_path / "plan.md"
    assert updated_plan_body("Architect", path, None) is None
    path.write_text("# A\n", encoding="utf-8")
    assert updated_plan_body("Code", path, None) is None
    assert updated_plan_body("Architect", path, "# A\n") is None
    assert updated_plan_body("Architect", path, None) == "# A\n"
    path.write_text("# B\n", encoding="utf-8")
    assert updated_plan_body("Architect", path, "# A\n") == "# B\n"


async def test_architect_turn_then_approve_and_quit_like_cli(tmp_path: Path):
    body = "# Touch planned.txt\n\nCreate planned.txt.\n"
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
                                    "name": "files",
                                    "arguments": json.dumps(
                                        {"action": "write", "path": "hello.py", "content": "x"}
                                    ),
                                },
                            }
                        ],
                    ),
                    (
                        "",
                        [
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {
                                    "name": "files",
                                    "arguments": json.dumps(
                                        {"action": "write", "path": "plan.md", "content": body}
                                    ),
                                },
                            }
                        ],
                    ),
                    ("plan ready", []),
                    ("executed", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    plans = PlanStore(tmp_path / "plans")
    before = None
    await master.turn("plan a touch file", mode="Architect")
    found = updated_plan_body("Architect", tmp_path / "plan.md", before)
    assert found == body
    assert not (tmp_path / "hello.py").exists()
    plan = plans.upsert_waiting("sess1", found)
    assert plan_action("a", waiting=True)[0] == "approve"
    approved = plans.set_status(plan.id, "approved")
    assert approved.status == "approved"
    reply = await master.turn(execute_prompt(approved), skip_clarify=True, mode="Code")
    assert reply == "executed"
    assert "Touch planned.txt" in execute_prompt(approved)

    other = plans.upsert_waiting("sess1", "# Next\n")
    assert other.id != plan.id
    assert plan_action("q", waiting=True)[0] == "quit"
    assert plans.set_status(other.id, "discarded").status == "discarded"
    rows = plans.list(session_id="sess1")
    assert {r["status"] for r in rows} == {"approved", "discarded"}


async def test_architect_blocks_project_write_allows_plan_md(tmp_path: Path):
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
                                    "name": "files",
                                    "arguments": json.dumps(
                                        {"action": "write", "path": "hello.py", "content": "x"}
                                    ),
                                },
                            }
                        ],
                    ),
                    (
                        "",
                        [
                            {
                                "id": "c2",
                                "type": "function",
                                "function": {
                                    "name": "files",
                                    "arguments": json.dumps(
                                        {
                                            "action": "write",
                                            "path": "plan.md",
                                            "content": "# Plan\n\nSteps\n",
                                        }
                                    ),
                                },
                            }
                        ],
                    ),
                    ("plan written", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.architect_prompt = "Write only plan.md."
    reply = await master.turn("plan a touch file", mode="Architect")
    assert reply == "plan written"
    assert not (tmp_path / "hello.py").exists()
    assert (tmp_path / "plan.md").is_file()
    assert "Plan" in (tmp_path / "plan.md").read_text(encoding="utf-8")
    blob = json.dumps(memory.latest(40))
    assert "architect mode forbids" in blob
    sys_msg = next(c[1][0]["content"] for c in fake.calls if c[0] == "master-a")
    assert "Write only plan.md" in sys_msg


async def test_architect_shell_does_not_raise_card(tmp_path: Path):
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
                                    "arguments": '{"command":"rm -rf nope"}',
                                },
                            }
                        ],
                    ),
                    ("blocked", []),
                ],
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    await master.turn("wipe it", mode="Architect")
    assert gate.pending() == []
    blob = json.dumps(memory.latest(20))
    assert "architect mode forbids" in blob


async def test_background_task_stays_code_in_architect_session(tmp_path: Path):
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": '{"clarity":"clear"}',
                "master-a": "ok",
            }
        }
    )
    bus, gate, tasks, registry, memory, master = _stack(tmp_path, fake)
    master.mode = "Architect"
    master.architect_prompt = "plan only"

    async def worker(task):
        return await master.turn("hi", task=task)

    t = tasks.spawn("bg", worker)
    for _ in range(40):
        if t.status in ("done", "failed"):
            break
        await asyncio.sleep(0.02)
    sys_msgs = [c[1][0]["content"] for c in fake.calls if c[0] == "master-a"]
    assert sys_msgs
    assert all("plan only" not in m for m in sys_msgs)
