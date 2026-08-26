"""Run the Phase 2 suite and write {success%, latency, token cost, interventions, cost per accepted outcome}."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Awaitable, Callable


@dataclass
class ScenarioResult:
    name: str
    success: bool
    latency_ms: float = 0.0
    token_cost: float = 0.0
    human_interventions: int = 0
    trace: list[dict] = field(default_factory=list)
    error: str | None = None


Scenario = Callable[[], Awaitable[ScenarioResult]]


def summarize(results: list[ScenarioResult], started: str, finished: str) -> dict:
    n = len(results)
    wins = sum(1 for r in results if r.success)
    tokens = sum(r.token_cost for r in results)
    humans = sum(r.human_interventions for r in results)
    latency = sum(r.latency_ms for r in results)
    accepted = wins
    return {
        "started_at": started,
        "finished_at": finished,
        "success_pct": (100.0 * wins / n) if n else 0.0,
        "latency_ms": round(latency, 3),
        "token_cost": tokens,
        "human_interventions": humans,
        "cost_per_accepted_outcome": (tokens / accepted) if accepted else None,
        "scenarios": [
            {
                "name": r.name,
                "success": r.success,
                "latency_ms": round(r.latency_ms, 3),
                "token_cost": r.token_cost,
                "human_interventions": r.human_interventions,
                "cost_per_accepted_outcome": r.token_cost if r.success else None,
                "trace": r.trace,
                "error": r.error,
            }
            for r in results
        ],
    }


async def run(scenarios: list[Scenario], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    results: list[ScenarioResult] = []
    for scen in scenarios:
        t0 = perf_counter()
        try:
            result = await scen()
        except Exception as exc:
            result = ScenarioResult(name=getattr(scen, "name", scen.__name__), success=False, error=str(exc))
        result.latency_ms = (perf_counter() - t0) * 1000
        results.append(result)
    finished = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}.json"
    payload = summarize(results, started.isoformat(), finished.isoformat())
    payload["out"] = str(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


async def run_suite(root: Path) -> Path:
    from evals.scenarios import default_suite

    out = root / "evals" / "runs"
    return await run(default_suite(root), out)
