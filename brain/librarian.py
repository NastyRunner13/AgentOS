"""Librarian node: episodes in, proposal ids out. Never writes facts/entities/edges."""

from __future__ import annotations

import json
import re

from brain.registry import Registry
from kernel import Bus
from memory import Episodic

DEFAULT_PROMPT = """\
Extract durable facts, people, projects, and preferences from the episodes.
Reply JSON only, no markdown:
{"candidates":[{"kind":"fact"|"entity"|"edge","statement":"","entity_kind":"Person"|"Project"|"Preference","name":"","attrs":{},"src":"","rel":"OWNS"|"ABOUT"|"SUPERSEDES","dst":"","confidence":0.8,"supersedes":null}]}
Skip one-off chatter. Skip anything listed as known or rejected.
Empty candidates array if nothing new.
"""


def _json_object(text: str) -> dict | None:
    text = (text or "").strip()
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        val = json.loads(match.group(0))
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        return None


def parse_candidates(raw: str) -> list[dict] | None:
    obj = _json_object(raw)
    if obj is None or "candidates" not in obj:
        return None
    items = obj.get("candidates")
    if not isinstance(items, list):
        return None
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "fact")
        if kind not in ("fact", "entity", "edge", "preference"):
            continue
        out.append(item)
    return out


async def draft(memory: Episodic, registry: Registry, bus: Bus | None = None) -> dict:
    """Bounded consolidate pass. Schema: {status, proposal_ids, stuck, evidence, question}."""
    if memory.stage < 1:
        return {
            "status": "skipped",
            "proposal_ids": [],
            "stuck": False,
            "evidence": None,
            "question": None,
            "detail": "stage 0: librarian locked",
        }
    if memory.librarian_stuck:
        return {
            "status": "stuck",
            "proposal_ids": [],
            "stuck": True,
            "evidence": {"detail": "librarian already stuck"},
            "question": "Consolidation is stuck on earlier bad drafts. Skip or inspect /proposals?",
        }

    limit = int(memory.cfg.get("consolidate_episode_limit", 40))
    cap = int(memory.cfg.get("max_proposals_per_pass", 10))
    if bus is not None:
        memory.bus = bus
    episodes = memory.latest(limit)
    known = [f["statement"] for f in memory.valid_facts()]
    rejected = memory.rejected_labels()

    prompt = ((registry.cfg.get("prompts") or {}).get("librarian") or DEFAULT_PROMPT).strip()
    body = json.dumps({"episodes": episodes, "known": known, "rejected": rejected})
    try:
        raw, _ = await registry.complete(
            "fast",
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": body},
            ],
        )
    except Exception as exc:
        n = memory.librarian_fail()
        evidence = {"error": str(exc), "fails": n}
        stuck = memory.librarian_stuck
        return {
            "status": "stuck" if stuck else "error",
            "proposal_ids": [],
            "stuck": stuck,
            "evidence": evidence,
            "question": "Librarian failed to run. Skip consolidation?" if stuck else None,
        }

    candidates = parse_candidates(raw)
    if candidates is None:
        n = memory.librarian_fail()
        evidence = {"raw": raw[:1000], "fails": n}
        stuck = memory.librarian_stuck
        return {
            "status": "stuck" if stuck else "invalid",
            "proposal_ids": [],
            "stuck": stuck,
            "evidence": evidence,
            "question": (
                "I couldn't extract memory proposals (invalid JSON). Skip consolidation?"
                if stuck
                else None
            ),
        }

    memory.librarian_ok()
    ids: list[str] = []
    for item in candidates[:cap]:
        pid = memory.propose(item)
        if pid and pid not in ids:
            ids.append(pid)
    return {
        "status": "ok",
        "proposal_ids": ids,
        "stuck": False,
        "evidence": None,
        "question": None,
    }
