"""Phase 3 done-conditions from AGENTARCH.md."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from brain.librarian import draft, parse_candidates
from brain.registry import FakeAdapter, Registry
from evals.scenarios import memory_recall_after_n, proposals_never_auto_applied
from memory import AUTO_CONSOLIDATE_UNLOCKED, Episodic

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".venv", "venv", "__pycache__", "evals", "tests"}


def _registry(script: dict, model_id: str = "fast-a") -> Registry:
    fake = FakeAdapter({"script": script})
    return Registry(
        {
            "default_provider": "fake",
            "providers": {"fake": {"kind": "fake"}},
            "roles": {"fast": model_id, "master": model_id},
        },
        extra={"fake": fake},
    )


async def test_a_recall_after_n_confirmed_facts_alone(tmp_path: Path):
    result = await memory_recall_after_n(tmp_path)
    assert result.success, result.error or result.trace


async def test_b_proposals_in_queue_never_auto_applied(tmp_path: Path):
    result = await proposals_never_auto_applied(tmp_path)
    assert result.success, result.error or result.trace
    mem = Episodic(tmp_path / "fresh.db")
    cards = []

    class Capture:
        def publish(self, topic, payload):
            if topic == "approval.request":
                cards.append(payload)

    mem.bus = Capture()
    pid = mem.propose({"kind": "fact", "statement": "Editor is neovim"})
    assert pid
    assert mem.valid_facts() == []
    assert cards and cards[0]["id"] == pid
    assert cards[0]["kind"] == "memory"
    applied = mem.approve([pid])
    assert applied == [pid]
    assert mem.valid_facts()[0]["statement"] == "Editor is neovim"
    mem.close()


def test_c_grep_no_automatic_graph_vector_writes():
    arch = (ROOT / "AGENTARCH.md").read_text(encoding="utf-8")
    assert "STAGE 2 AUTO-CONSOLIDATE: LOCKED" in arch
    mem_cfg = yaml.safe_load((ROOT / "config" / "memory.yaml").read_text(encoding="utf-8"))
    assert mem_cfg["stage"] in (0, 1)
    assert AUTO_CONSOLIDATE_UNLOCKED is False

    forbidden_imports = re.compile(r"^\s*(import|from)\s+(kuzu|lancedb|chromadb|chroma)\b", re.M)
    insert_graph = re.compile(r"INSERT INTO (facts|entities|edges)\b")
    writers = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_PARTS or part.endswith(".egg-info") for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        assert "AUTO_CONSOLIDATE_UNLOCKED = True" not in text, path
        assert not forbidden_imports.search(text), path
        if insert_graph.search(text):
            writers.append(path.relative_to(ROOT).as_posix())
    assert writers == ["memory/__init__.py"], writers

    src = (ROOT / "memory" / "__init__.py").read_text(encoding="utf-8")
    propose_fn = src.split("def propose(")[1].split("def approve(")[0]
    apply_fn = src.split("def _apply(")[1].split("def _fingerprint(")[0]
    for table in ("facts", "entities", "edges"):
        assert f"INSERT INTO {table}" not in propose_fn
        assert f"INSERT INTO {table}" in apply_fn


async def test_supersede_sets_valid_to_never_deletes(tmp_path: Path):
    mem = Episodic(tmp_path / "g.db")
    old = mem.propose({"kind": "fact", "statement": "Standup is at 09:00"})
    mem.approve([old])
    fid = mem.valid_facts()[0]["id"]
    new = mem.propose({"kind": "fact", "statement": "Standup is at 10:00", "supersedes": fid})
    mem.approve([new])
    current = mem.valid_facts()
    assert [f["statement"] for f in current] == ["Standup is at 10:00"]
    rows = mem._db.execute("SELECT statement, valid_to FROM facts ORDER BY valid_from").fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "Standup is at 09:00" and rows[0][1]
    assert rows[1][0] == "Standup is at 10:00" and rows[1][1] is None
    rels = {e["rel"] for e in mem.edges()}
    assert "SUPERSEDES" in rels
    mem.close()


async def test_bulk_approve_and_reject(tmp_path: Path):
    mem = Episodic(tmp_path / "b.db")
    a = mem.propose({"kind": "fact", "statement": "Name is Prince"})
    b = mem.propose({"kind": "entity", "entity_kind": "Person", "name": "Prince", "attrs": {"relation": "user"}})
    c = mem.propose({"kind": "fact", "statement": "Skip this"})
    mem.reject([c])
    applied = mem.approve_all()
    assert set(applied) == {a, b}
    statements = {f["statement"] for f in mem.valid_facts()}
    assert statements == {"Name is Prince"}
    assert mem.entities()[0]["name"] == "Prince"
    assert "Skip this" not in {f["statement"] for f in mem.recall("skip")}
    assert not mem.pending()
    mem.close()


async def test_duplicate_and_rejected_not_reproposed(tmp_path: Path):
    mem = Episodic(tmp_path / "d.db")
    p1 = mem.propose({"kind": "fact", "statement": "Uses dark mode"})
    p2 = mem.propose({"kind": "fact", "statement": "Uses dark mode"})
    assert p1 == p2
    mem.reject([p1])
    assert mem.propose({"kind": "fact", "statement": "Uses dark mode"}) is None
    mem.close()


async def test_stage_0_skips_librarian(tmp_path: Path):
    mem = Episodic(tmp_path / "s0.db", cfg={"stage": 0})
    mem.write("turn", content="Standup at 9", role="user")
    result = await draft(mem, _registry({"fast-a": '{"candidates":[{"kind":"fact","statement":"x"}]}'}))
    assert result["status"] == "skipped"
    assert mem.pending() == []
    mem.close()


async def test_librarian_stuck_after_two_bad_drafts(tmp_path: Path):
    mem = Episodic(tmp_path / "st.db", cfg={"stage": 1, "librarian_fail_stuck": 2})
    mem.write("turn", content="hello", role="user")
    registry = _registry({"fast-a": ["not json", "still not", "ignored"]})
    first = await draft(mem, registry)
    assert first["stuck"] is False
    second = await draft(mem, registry)
    assert second["stuck"] is True
    assert second["evidence"]
    assert second["question"]
    third = await draft(mem, registry)
    assert third["stuck"] is True
    assert mem.pending() == []
    mem.close()


def test_parse_candidates_drops_junk():
    assert parse_candidates("nope") is None
    parsed = parse_candidates('{"candidates":[{"kind":"fact","statement":"ok"},{"kind":"nope"},7]}')
    assert parsed == [{"kind": "fact", "statement": "ok"}]


def test_episodic_search_and_latest_order(tmp_path: Path):
    mem = Episodic(tmp_path / "fts.db")
    mem.write("turn", content="alpha one", role="user")
    mem.write("turn", content="beta two", role="user")
    mem.write("turn", content="alpha three", role="assistant")
    latest = mem.latest(2)
    assert [r["content"] for r in latest] == ["beta two", "alpha three"]
    hits = mem.search("alpha")
    assert {h["content"] for h in hits} == {"alpha one", "alpha three"}
    mem.close()
