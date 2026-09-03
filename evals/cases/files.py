"""Files and permission-card eval scenarios."""

from __future__ import annotations

import asyncio
from pathlib import Path

from evals.fakes import perm
from evals.harness import ScenarioResult
from kernel import Bus, Gate
from tools import NativeTools


async def file_write_roundtrip(root: Path) -> ScenarioResult:
    cfg = perm(root)
    tools = NativeTools(root, cfg)
    wrote = tools.files({"action": "write", "path": "out.txt", "content": "ok"})
    read = tools.files({"action": "read", "path": "out.txt"})
    ok = "ok" in read and "wrote" in wrote
    return ScenarioResult(
        "file_write_roundtrip",
        ok,
        trace=[{"action": "files.write", "path": "none", "verified": ok, "verify": {"ok": ok, "detail": read}}],
    )


async def ring2_card_blocks(root: Path) -> ScenarioResult:
    cfg = perm(root)
    bus = Bus()
    gate = Gate(cfg, bus)
    cards = bus.subscribe("approval.request")
    task = asyncio.create_task(gate.check("shell", {"command": "Write-Host pwned"}))
    card = await asyncio.wait_for(cards.get(), 2)
    denied = gate.resolve(card["id"], False)
    allowed = await asyncio.wait_for(task, 2)
    ok = card["ring"] == 2 and denied and allowed is False
    return ScenarioResult(
        "ring2_card_blocks",
        ok,
        human_interventions=1,
        trace=[
            {
                "action": "shell",
                "path": "none",
                "verified": True,
                "verify": {"ok": True, "detail": "blocked until card, then denied"},
            }
        ],
    )
