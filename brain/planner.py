"""Long-horizon milestone planner and state checkpoint engine for AgentOS.

Follows PRINCIPLES.md:
- Work is a graph of nodes (milestones).
- Three files a loop reads: charter, resume, L2 episodic.
- Maker never accepts: Independent verifier checks machine signals.
- Stuck protocol: 2 failed verifications -> halt and attach evidence.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Milestone:
    id: str
    description: str
    status: str = "pending"  # "pending", "in_progress", "verified", "failed", "stuck"
    verifier: str = "machine"  # "exit_code_zero", "file_exists", "text_match", "dom_element", "manual"
    verifier_target: str = ""  # file path, expected string, or command
    result: str = ""
    failures: int = 0
    evidence: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResumeState:
    task_id: str
    goal: str
    charter: list[str] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    current_index: int = 0
    rejected: list[dict] = field(default_factory=list)
    spend_tokens: int = 0
    completed: bool = False

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "charter": self.charter,
            "milestones": [m.as_dict() for m in self.milestones],
            "current_index": self.current_index,
            "rejected": self.rejected,
            "spend_tokens": self.spend_tokens,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ResumeState:
        milestones = [
            Milestone(**m) if isinstance(m, dict) else m
            for m in data.get("milestones", [])
        ]
        return cls(
            task_id=str(data.get("task_id", "")),
            goal=str(data.get("goal", "")),
            charter=list(data.get("charter", [])),
            milestones=milestones,
            current_index=int(data.get("current_index", 0)),
            rejected=list(data.get("rejected", [])),
            spend_tokens=int(data.get("spend_tokens", 0)),
            completed=bool(data.get("completed", False)),
        )


class CheckpointStore:
    """Manages reading and persisting resume.json checkpoint files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    def _path(self, task_id: str) -> Path:
        p = self.data_dir / "tasks" / task_id / "resume.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, state: ResumeState) -> None:
        path = self._path(state.task_id)
        path.write_text(json.dumps(state.as_dict(), indent=2), encoding="utf-8")

    def load(self, task_id: str) -> ResumeState | None:
        path = self._path(task_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ResumeState.from_dict(data)
        except Exception:
            return None


def verify_signal(milestone: Milestone, actual_output: str, root_path: Path | None = None) -> tuple[bool, str]:
    """Independent machine verifier for milestone outcomes (Maker never accepts)."""
    kind = milestone.verifier
    target = milestone.verifier_target.strip()
    out = (actual_output or "").strip()

    if kind == "exit_code_zero":
        import re
        match = re.search(r"\bexit\s+(\d+)", out)
        if match and match.group(1) != "0":
            return False, f"Non-zero exit status ({match.group(1)}) detected: {out[:200]}"
        if "timed out" in out.lower():
            return False, "Command execution timed out"
        return True, "Exit code zero verified"

    if kind == "file_exists" and target:
        p = Path(target)
        if root_path and not p.is_absolute():
            p = root_path / p
        if p.exists():
            return True, f"File {target} exists on disk ({p.stat().st_size} bytes)"
        return False, f"File {target} was not found"

    if kind == "text_match" and target:
        if target.lower() in out.lower():
            return True, f"Found target text {target!r} in output"
        return False, f"Target text {target!r} not found in output"

    if kind == "dom_element" and target:
        if f'"{target}"' in out or f"'{target}'" in out or target in out:
            return True, f"DOM element {target!r} observed in page"
        return False, f"DOM element {target!r} missing from state"

    # Default fallback: check if output indicates no error
    has_err = any(e in out.lower() for e in ("error:", "fatal:", "exception:", "traceback", "failed"))
    return (not has_err), ("No error keywords found" if not has_err else f"Error detected: {out[:200]}")


class MilestonePlanner:
    """Orchestrates milestone decomposition, verification, and stuck recovery."""

    def __init__(self, store: CheckpointStore, root: Path, max_fails: int = 2) -> None:
        self.store = store
        self.root = root
        self.max_fails = max_fails

    def create_plan(self, task_id: str, goal: str, milestones: list[dict], charter: list[str] | None = None) -> ResumeState:
        ms = [
            Milestone(
                id=f"m{i + 1}",
                description=str(m.get("description", "")),
                verifier=str(m.get("verifier", "machine")),
                verifier_target=str(m.get("target", "")),
            )
            for i, m in enumerate(milestones)
        ]
        state = ResumeState(
            task_id=task_id,
            goal=goal,
            charter=charter or [],
            milestones=ms,
            current_index=0,
        )
        self.store.save(state)
        return state

    def record_step(self, state: ResumeState, step_output: str) -> dict:
        """Evaluates active milestone with independent verifier and updates state."""
        if state.current_index >= len(state.milestones):
            state.completed = True
            self.store.save(state)
            return {"status": "completed", "message": "All milestones verified"}

        current = state.milestones[state.current_index]
        current.result = step_output[:1000]
        ok, reason = verify_signal(current, step_output, self.root)

        if ok:
            current.status = "verified"
            current.failures = 0
            current.evidence = reason
            state.current_index += 1
            if state.current_index >= len(state.milestones):
                state.completed = True
            self.store.save(state)
            return {"status": "verified", "milestone": current.id, "reason": reason}

        current.failures += 1
        current.evidence = reason
        state.rejected.append({
            "milestone": current.id,
            "attempt": current.failures,
            "reason": reason,
            "output": step_output[:500],
        })

        if current.failures >= self.max_fails:
            current.status = "stuck"
            self.store.save(state)
            return {
                "status": "stuck",
                "milestone": current.id,
                "question": f"Milestone '{current.description}' failed verification twice ({reason}). How should I adjust?",
                "evidence": reason,
            }

        current.status = "failed"
        self.store.save(state)
        return {"status": "failed", "milestone": current.id, "reason": reason, "retry": current.failures}
