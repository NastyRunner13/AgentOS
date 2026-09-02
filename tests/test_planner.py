"""Tests for MilestonePlanner, CheckpointStore, and Maker-Checker verifier."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from brain.planner import CheckpointStore, Milestone, MilestonePlanner, ResumeState, verify_signal


def test_checkpoint_store_save_and_load(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    state = ResumeState(
        task_id="task-test-1",
        goal="Autonomous fix and verify",
        charter=["Never commit broken code", "Ring 2 requires card"],
        milestones=[
            Milestone(id="m1", description="Inspect issue", verifier="text_match", verifier_target="Issue #42"),
            Milestone(id="m2", description="Run build", verifier="exit_code_zero"),
        ],
    )
    store.save(state)
    loaded = store.load("task-test-1")
    assert loaded is not None
    assert loaded.task_id == "task-test-1"
    assert loaded.goal == "Autonomous fix and verify"
    assert len(loaded.milestones) == 2
    assert loaded.milestones[0].description == "Inspect issue"
    assert loaded.charter[0] == "Never commit broken code"


def test_verify_signal_exit_code():
    m = Milestone(id="m1", description="Build", verifier="exit_code_zero")
    ok, _ = verify_signal(m, "Build completed successfully.\nexit 0")
    assert ok is True

    bad, reason = verify_signal(m, "Build failed: error in main.rs\nexit 1")
    assert bad is False
    assert "Non-zero exit" in reason


def test_verify_signal_file_exists(tmp_path: Path):
    target = tmp_path / "artifacts" / "report.pdf"
    m = Milestone(id="m1", description="Write report", verifier="file_exists", verifier_target=str(target))
    
    ok, _ = verify_signal(m, "Generated report", root_path=tmp_path)
    assert ok is False

    target.parent.mkdir(parents=True)
    target.write_text("dummy", encoding="utf-8")
    ok, reason = verify_signal(m, "Generated report", root_path=tmp_path)
    assert ok is True
    assert "exists on disk" in reason


def test_milestone_planner_maker_checker_and_stuck_protocol(tmp_path: Path):
    store = CheckpointStore(tmp_path)
    planner = MilestonePlanner(store, tmp_path, max_fails=2)

    plan = planner.create_plan(
        task_id="task-dev-1",
        goal="Resolve GitHub bug",
        milestones=[
            {"description": "Reproduce bug", "verifier": "text_match", "target": "Reproduction verified"},
            {"description": "Apply fix and build", "verifier": "exit_code_zero"},
        ],
    )
    assert len(plan.milestones) == 2
    assert plan.current_index == 0

    # Step 1: Passes verification
    res1 = planner.record_step(plan, "Bug confirmed: Reproduction verified")
    assert res1["status"] == "verified"
    assert plan.current_index == 1

    # Step 2: Attempt 1 fails
    res2 = planner.record_step(plan, "Build error: SyntaxError\nexit 2")
    assert res2["status"] == "failed"
    assert res2["retry"] == 1
    assert plan.current_index == 1

    # Step 2: Attempt 2 fails -> Triggers STUCK protocol
    res3 = planner.record_step(plan, "Build error: SyntaxError\nexit 2")
    assert res3["status"] == "stuck"
    assert "question" in res3
    assert plan.milestones[1].status == "stuck"
