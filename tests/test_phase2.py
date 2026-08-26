"""Phase 2 done-conditions from AGENTARCH.md."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evals.harness import run_suite
from evals.scenarios import CapturingPixels, ScriptedA11y, _operator
from tools import NativeTools
from tools.operator import Node

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "success_pct",
    "latency_ms",
    "token_cost",
    "human_interventions",
    "cost_per_accepted_outcome",
)


def _scenario(data: dict, name: str) -> dict:
    return next(s for s in data["scenarios"] if s["name"] == name)


async def test_a_suite_writes_metrics_json(tmp_path):
    path = await run_suite(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.is_file()
    for key in KEYS:
        assert key in data
    assert data["success_pct"] == 100.0
    assert len(data["scenarios"]) >= 4


def test_a_one_command_writes_json(tmp_path):
    proc = subprocess.run(
        [sys.executable, "main.py", "--eval", "--root", str(tmp_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    runs = [p for p in (tmp_path / "evals" / "runs").glob("*.json") if p.name != "work"]
    assert runs, proc.stdout
    data = json.loads(runs[0].read_text(encoding="utf-8"))
    for key in KEYS:
        assert key in data


async def test_b_every_operator_action_has_verify(tmp_path):
    data = json.loads((await run_suite(tmp_path)).read_text(encoding="utf-8"))
    n = 0
    for scen in data["scenarios"]:
        assert scen["trace"], scen["name"]
        for step in scen["trace"]:
            assert "verify" in step, step
            assert "ok" in step["verify"], step
            n += 1
    assert n > 0


async def test_c_broken_scenario_stuck_with_evidence(tmp_path):
    data = json.loads((await run_suite(tmp_path)).read_text(encoding="utf-8"))
    stuck = _scenario(data, "stuck_on_broken_verify")
    assert stuck["success"] is True
    flags = [t for t in stuck["trace"] if t.get("stuck")]
    assert flags
    item = flags[0]
    assert item["verified"] is False
    assert item["evidence"]
    assert item["question"]
    assert item["path"] == "a11y"
    assert any(t["action"] == "click" and t.get("stuck") for t in stuck["trace"])


async def test_d_pixels_only_when_a11y_unusable(tmp_path):
    data = json.loads((await run_suite(tmp_path)).read_text(encoding="utf-8"))
    a11y = next(t for t in _scenario(data, "a11y_click_verified")["trace"] if t["action"] == "click")
    assert a11y["path"] == "a11y"
    empty = next(t for t in _scenario(data, "pixels_when_a11y_empty")["trace"] if t["action"] == "click")
    assert empty["path"] == "pixels"
    skip = next(
        t for t in _scenario(data, "pixels_skipped_when_a11y_usable")["trace"] if t["action"] == "click"
    )
    assert skip["path"] == "a11y"
    assert skip["verified"] is False


async def test_low_confidence_ground_does_not_click(tmp_path):
    a11y = ScriptedA11y(empty=True)
    pixels = CapturingPixels()

    async def ground(png: bytes) -> dict:
        return {"coords": [1, 1], "confidence": 0.1}

    op = _operator(tmp_path, a11y, pixels, ground=ground)
    raw = await op.execute({"action": "click", "app": "notepad"})
    item = json.loads(raw)
    assert item["stuck"] is True
    assert item["path"] == "pixels"
    assert pixels.clicks == []
    assert item["evidence"]


async def test_computer_tool_dispatches(tmp_path):
    a11y = ScriptedA11y([Node("e1", "button", "OK")])
    orig = a11y.click

    async def click(ref: str) -> None:
        await orig(ref)
        a11y.document = "OK clicked"

    a11y.click = click
    op = _operator(tmp_path, a11y, CapturingPixels())
    tools = NativeTools(tmp_path, {"files": {"approved_roots": ["."]}}, operator=op)
    await tools.execute("computer", {"action": "open", "app": "notepad"})
    raw = await tools.execute(
        "computer", {"action": "click", "app": "notepad", "ref": "e1", "expect": "OK clicked"}
    )
    item = json.loads(raw)
    assert item["path"] == "a11y"
    assert item["verified"] is True
    assert item["verify"]["ok"] is True


async def test_type_verified_and_snapshot_untrusted(tmp_path):
    a11y = ScriptedA11y([Node("e2", "textbox", "Name")])
    op = _operator(tmp_path, a11y, CapturingPixels())
    await op.execute({"action": "open", "app": "notepad"})
    raw = await op.execute({"action": "type", "app": "notepad", "ref": "e2", "text": "Ada"})
    item = json.loads(raw)
    assert item["verified"] is True
    assert item["path"] == "a11y"
    snap = json.loads(await op.execute({"action": "snapshot", "app": "notepad"}))
    assert snap["verified"] is True
    assert "<untrusted source=\"screen\">" in snap["tree"]


async def test_unknown_action_and_stuck_blocks_mutate(tmp_path):
    a11y = ScriptedA11y([Node("e1", "button", "Go")])
    op = _operator(tmp_path, a11y, CapturingPixels())
    bad = json.loads(await op.execute({"action": "drag", "app": "notepad"}))
    assert bad["verified"] is False
    await op.execute({"action": "open", "app": "notepad"})
    await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Finished"})
    stuck = json.loads(await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Finished"}))
    assert stuck["stuck"] is True
    blocked = json.loads(await op.execute({"action": "click", "app": "notepad", "ref": "e1"}))
    assert blocked["stuck"] is True
    assert a11y.clicks == ["e1", "e1"]
