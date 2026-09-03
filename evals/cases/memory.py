"""Memory stage-1 eval scenarios."""

from __future__ import annotations

import json
from pathlib import Path

from evals.harness import ScenarioResult
from memory import Episodic


async def memory_recall_after_n(root: Path) -> ScenarioResult:
    mem = Episodic(root / "recall.db")
    pid = mem.propose({"kind": "fact", "statement": "Standup is at 09:00", "confidence": 1.0})
    mem.approve([pid])
    for i in range(12):
        mem.write("turn", content=f"unrelated chatter {i} about the weather", role="user")
    leaked_pending = mem.propose({"kind": "fact", "statement": "Favorite color is blue", "confidence": 1.0})
    hits = mem.recall("when is standup?")
    statements = [h["statement"] for h in hits]
    leaked_turns = any("unrelated chatter" in s for s in statements)
    leaked_unapproved = any("blue" in s.lower() for s in statements)
    ok = (
        pid is not None
        and leaked_pending is not None
        and any("09:00" in s for s in statements)
        and not leaked_turns
        and not leaked_unapproved
        and mem.count() >= 12
        and all(r["kind"] == "turn" for r in mem.latest(12))
    )
    mem.close()
    return ScenarioResult(
        "memory_recall_after_n",
        ok,
        trace=[
            {
                "action": "recall",
                "path": "none",
                "verified": ok,
                "verify": {"ok": ok, "detail": f"hits={statements} pending={leaked_pending}"},
            }
        ],
    )


async def proposals_never_auto_applied(root: Path) -> ScenarioResult:
    from brain.librarian import draft
    from brain.registry import FakeAdapter, Registry

    mem = Episodic(root / "proposals.db", cfg={"stage": 1})
    mem.write("turn", content="My standup is at 9am every weekday.", role="user")
    fake = FakeAdapter(
        {
            "script": {
                "fast-a": json.dumps(
                    {
                        "candidates": [
                            {"kind": "fact", "statement": "Standup is at 09:00", "confidence": 0.9}
                        ]
                    }
                )
            }
        }
    )
    registry = Registry(
        {
            "default_provider": "fake",
            "providers": {"fake": {"kind": "fake"}},
            "roles": {"fast": "fast-a", "master": "fast-a"},
        },
        extra={"fake": fake},
    )
    result = await draft(mem, registry)
    facts_before = mem.valid_facts()
    pending = mem.pending()
    ok = (
        result["status"] == "ok"
        and result["proposal_ids"]
        and not facts_before
        and len(pending) == 1
        and pending[0]["status"] == "pending"
    )
    mem.close()
    return ScenarioResult(
        "proposals_never_auto_applied",
        ok,
        human_interventions=1,
        trace=[
            {
                "action": "kb_consolidate",
                "path": "none",
                "verified": ok,
                "verify": {"ok": ok, "detail": json.dumps(result)},
            }
        ],
    )
