"""Repeatable Phase 2 suite. Fakes, not a live desktop — same operator code path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml

from evals.harness import ScenarioResult
from kernel import Bus, Gate
from memory import Episodic
from tools import NativeTools
from tools.operator import Node, Operator


def _perm(root: Path) -> dict:
    path = root / "config" / "permissions.yaml"
    if path.is_file():
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "operator": {
            "max_verify_failures": 2,
            "min_ground_confidence": 0.5,
            "allowlist": {"notepad": {"exe": "notepad.exe"}, "browser": {"kind": "playwright"}},
            "ring": 1,
            "ring_other": 2,
        },
        "card": {"expiry_seconds": 300, "expire_action": "deny"},
        "shell": {"ring_other": 2, "allowlist": ["echo"]},
        "files": {"approved_roots": ["."], "read_ring": 0, "write_ring": 1},
    }


class ScriptedA11y:
    def __init__(self, elements: list[Node] | None = None, *, empty: bool = False) -> None:
        self.elements = [] if empty else list(elements or [Node("e1", "button", "OK")])
        self.clicks: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.document = ""
        self.keys_sent: list[str] = []

    async def open(self, app: str, url=None) -> None:
        self.opened.append(app)
        self.document = f"opened {app}"

    async def snapshot(self, app: str) -> list[Node]:
        return list(self.elements)

    async def click(self, ref: str) -> None:
        self.clicks.append(ref)

    async def type(self, ref: str, text: str) -> None:
        self.typed.append((ref, text))
        for n in self.elements:
            if n.ref == ref:
                n.value = text
        self.document += text

    async def keys(self, combo: str) -> None:
        self.keys_sent.append(combo)

    async def close(self, app: str) -> None:
        self.closed.append(app)

    async def read_state(self, app: str) -> str:
        names = " ".join(f"{n.name} {n.value}" for n in self.elements)
        return f"{self.document} {names}".strip()


class CapturingPixels:
    def __init__(self) -> None:
        self.shots = 0
        self.clicks: list[tuple[int, int]] = []
        self.typed: list[str] = []
        self.annotated = 0
        self.on_click = None

    async def screenshot(self) -> bytes:
        self.shots += 1
        return b"\x89PNG\r\n\x1a\n"

    async def annotate(self, png: bytes, leftover) -> bytes:
        self.annotated += 1
        return png

    async def click_xy(self, x: int, y: int) -> None:
        self.clicks.append((int(x), int(y)))
        if self.on_click:
            self.on_click()

    async def type_text(self, text: str) -> None:
        self.typed.append(text)


def _operator(root: Path, a11y, pixels, ground=None, session_grants=None) -> Operator:
    bus = Bus()
    memory = Episodic(root / "events.db")
    return Operator(
        _perm(root),
        bus,
        memory,
        root,
        a11y=a11y,
        pixels=pixels,
        ground=ground,
        session_grants=session_grants,
    )


def _load(raw: str) -> dict:
    return json.loads(raw)


async def a11y_click_verified(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y([Node("e1", "button", "Save")])
    orig = a11y.click

    async def click(ref: str) -> None:
        await orig(ref)
        a11y.document = "Saved"

    a11y.click = click
    pixels = CapturingPixels()
    op = _operator(root, a11y, pixels)
    await op.execute({"action": "open", "app": "notepad"})
    await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Saved"})
    last = op.trace[-1]
    ok = (
        last["path"] == "a11y"
        and last["verified"] is True
        and last["verify"]["ok"] is True
        and not pixels.clicks
        and a11y.clicks == ["e1"]
    )
    return ScenarioResult("a11y_click_verified", ok, trace=list(op.trace))


async def pixels_when_a11y_empty(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y(empty=True)
    pixels = CapturingPixels()

    def painted():
        a11y.document = "Done"

    pixels.on_click = painted

    async def ground(png: bytes) -> dict:
        return {"coords": [12, 40], "label": "1", "confidence": 0.9}

    op = _operator(root, a11y, pixels, ground=ground)
    await op.execute({"action": "open", "app": "notepad"})
    raw = await op.execute({"action": "click", "app": "notepad", "expect": "Done"})
    last = _load(raw)
    ok = (
        last["path"] == "pixels"
        and last["verified"] is True
        and pixels.clicks == [(12, 40)]
        and not a11y.clicks
    )
    return ScenarioResult("pixels_when_a11y_empty", ok, trace=list(op.trace))


async def stuck_on_broken_verify(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y([Node("e1", "button", "Go")])
    pixels = CapturingPixels()
    op = _operator(root, a11y, pixels)
    await op.execute({"action": "open", "app": "notepad"})
    await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Finished"})
    raw = await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Finished"})
    last = _load(raw)
    third = _load(await op.execute({"action": "click", "app": "notepad", "ref": "e1", "expect": "Finished"}))
    ok = (
        last["stuck"] is True
        and last["verified"] is False
        and last["evidence"] is not None
        and last["question"]
        and last["path"] == "a11y"
        and not pixels.clicks
        and a11y.clicks == ["e1", "e1"]
        and third["stuck"] is True
        and a11y.clicks == ["e1", "e1"]
    )
    return ScenarioResult(
        "stuck_on_broken_verify",
        ok,
        human_interventions=1 if last.get("stuck") else 0,
        trace=list(op.trace),
        error=None if ok else json.dumps(last),
    )


async def pixels_skipped_when_a11y_usable(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y([Node("e1", "button", "OK"), Node("e2", "textbox", "Name")])
    pixels = CapturingPixels()
    op = _operator(root, a11y, pixels)
    await op.execute({"action": "open", "app": "notepad"})
    raw = await op.execute({"action": "click", "app": "notepad", "ref": "missing"})
    last = _load(raw)
    ok = last["path"] == "a11y" and last["verified"] is False and not pixels.clicks and pixels.annotated == 0
    return ScenarioResult("pixels_skipped_when_a11y_usable", ok, trace=list(op.trace))


async def allowlist_rejects_unknown(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y()
    pixels = CapturingPixels()
    op = _operator(root, a11y, pixels)
    raw = await op.execute({"action": "open", "app": "steam"})
    last = _load(raw)
    ok = last["verified"] is False and not a11y.opened and "allowlist" in last["verify"]["detail"]
    return ScenarioResult("allowlist_rejects_unknown", ok, trace=list(op.trace))


async def unknown_app_card_then_grant(root: Path) -> ScenarioResult:
    grants: set[str] = set()
    perm = _perm(root)
    bus = Bus()
    gate = Gate(perm, bus, session_grants=grants)
    a11y = ScriptedA11y()
    op = Operator(
        perm,
        bus,
        Episodic(root / "events.db"),
        root,
        a11y=a11y,
        pixels=CapturingPixels(),
        session_grants=grants,
    )
    blocked = _load(await op.execute({"action": "open", "app": "steam"}))
    cards = bus.subscribe("approval.request")
    task = asyncio.create_task(gate.check("computer", {"action": "open", "app": "steam"}))
    card = await asyncio.wait_for(cards.get(), 2)
    gate.resolve(card["id"], True)
    allowed = await asyncio.wait_for(task, 2)
    opened = _load(await op.execute({"action": "open", "app": "steam"}))
    ok = (
        blocked["verified"] is False
        and "allowlist" in blocked["verify"]["detail"]
        and card["ring"] == 2
        and allowed is True
        and "steam" in grants
        and opened["verified"] is True
        and a11y.opened == ["steam"]
        and gate.classify("computer", {"action": "click", "app": "steam"}) == 1
    )
    return ScenarioResult(
        "unknown_app_card_then_grant",
        ok,
        human_interventions=1,
        trace=list(op.trace),
        error=None if ok else json.dumps({"blocked": blocked, "opened": opened, "grants": list(grants)}),
    )


async def file_write_roundtrip(root: Path) -> ScenarioResult:
    perm = _perm(root)
    tools = NativeTools(root, perm)
    wrote = tools.files({"action": "write", "path": "out.txt", "content": "ok"})
    read = tools.files({"action": "read", "path": "out.txt"})
    ok = "ok" in read and "wrote" in wrote
    return ScenarioResult(
        "file_write_roundtrip",
        ok,
        trace=[{"action": "files.write", "path": "none", "verified": ok, "verify": {"ok": ok, "detail": read}}],
    )


async def ring2_card_blocks(root: Path) -> ScenarioResult:
    perm = _perm(root)
    bus = Bus()
    gate = Gate(perm, bus)
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


async def research_query_cites_fetch(root: Path) -> ScenarioResult:
    """Offline: search then fetch, cite the URL, never claim success without tools."""
    import tools.web as webmod
    from brain.master import Master
    from brain.registry import FakeAdapter, Registry
    from kernel import TaskManager

    async def fake_search(query, perm_cfg, clip=None, **opts):
        return (
            '<untrusted source="web">\n'
            '[{"n":1,"title":"Example","url":"https://example.com/x","domain":"example.com","snippet":"about x"}]\n'
            "</untrusted>"
        )

    async def fake_fetch(url, perm_cfg, clip=None, **opts):
        return f'<untrusted source="web" url="{url}">\nExample Domain facts about x.\n</untrusted>'

    orig_search, orig_fetch = webmod.search, webmod.fetch
    webmod.search = fake_search
    webmod.fetch = fake_fetch
    try:
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
                        ("According to Example (https://example.com/x), facts about x.", []),
                    ],
                }
            }
        )
        perm = _perm(root)
        bus = Bus()
        gate = Gate(perm, bus)
        tasks = TaskManager(bus, concurrent_slots=2)
        registry = Registry(
            {
                "default_provider": "fake",
                "providers": {"fake": {"kind": "fake"}},
                "roles": {
                    "master": "master-a",
                    "fast": "fast-a",
                    "vision": "master-a",
                    "embeddings": "master-a",
                },
            },
            extra={"fake": fake},
        )
        memory = Episodic(root / "events.db")
        tools = NativeTools(root, perm)
        master = Master(
            registry,
            gate,
            tasks,
            memory,
            tools,
            bus,
            system_prompt="You are Friday.",
            clarify_prompt='Reply JSON {"clarity":"clear","questions":[],"assumption":""}',
            clarify=True,
            max_tool_steps=16,
        )
        reply = await master.turn("what is X (web)")
        tool_roles = [e["role"] for e in memory.latest(40) if e["kind"] == "tool"]
        search_row = next(e for e in memory.latest(40) if e.get("role") == "web_search")
        ok = (
            tool_roles[:2] == ["web_search", "web_fetch"]
            and "browser" not in tool_roles
            and "<untrusted" in search_row["content"]
            and "https://example.com/x" in reply
            and "facts about x" in reply.lower()
        )
        memory.close()
        return ScenarioResult(
            "research_query_cites_fetch",
            ok,
            trace=[
                {
                    "action": "web_search+web_fetch",
                    "path": "none",
                    "verified": ok,
                    "verify": {"ok": ok, "detail": f"roles={tool_roles} reply={reply[:120]}"},
                }
            ],
            error=None if ok else f"roles={tool_roles} reply={reply}",
        )
    finally:
        webmod.search = orig_search
        webmod.fetch = orig_fetch


def default_suite(root: Path) -> list:
    work = root / "evals" / "runs" / "work"
    work.mkdir(parents=True, exist_ok=True)

    def bind(fn, name: str):
        async def wrapped():
            slot = work / name
            slot.mkdir(parents=True, exist_ok=True)
            result = await fn(slot)
            result.name = name
            return result

        wrapped.__name__ = name
        return wrapped

    return [
        bind(a11y_click_verified, "a11y_click_verified"),
        bind(pixels_when_a11y_empty, "pixels_when_a11y_empty"),
        bind(stuck_on_broken_verify, "stuck_on_broken_verify"),
        bind(pixels_skipped_when_a11y_usable, "pixels_skipped_when_a11y_usable"),
        bind(allowlist_rejects_unknown, "allowlist_rejects_unknown"),
        bind(unknown_app_card_then_grant, "unknown_app_card_then_grant"),
        bind(file_write_roundtrip, "file_write_roundtrip"),
        bind(ring2_card_blocks, "ring2_card_blocks"),
        bind(memory_recall_after_n, "memory_recall_after_n"),
        bind(proposals_never_auto_applied, "proposals_never_auto_applied"),
        bind(research_query_cites_fetch, "research_query_cites_fetch"),
    ]
