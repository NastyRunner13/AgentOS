"""Operator / computer-use eval scenarios."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from evals.fakes import CapturingPixels, ScriptedA11y, operator, perm
from evals.harness import ScenarioResult
from kernel import Bus, Gate
from memory import Episodic
from tools.operator import Node, Operator


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
    op = operator(root, a11y, pixels)
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

    op = operator(root, a11y, pixels, ground=ground)
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
    op = operator(root, a11y, pixels)
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


async def xy_click_explicit(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y([Node("e1", "button", "OK")])
    pixels = CapturingPixels()
    op = operator(root, a11y, pixels)
    raw = await op.execute({"action": "click", "x": 40, "y": 80})
    last = _load(raw)
    ok = (
        last["path"] == "pixels"
        and last["verified"] is True
        and pixels.clicks == [(40, 80)]
        and not a11y.clicks
        and last.get("x") == 40
        and last.get("y") == 80
    )
    return ScenarioResult("xy_click_explicit", ok, trace=list(op.trace))


async def pixels_skipped_when_a11y_usable(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y([Node("e1", "button", "OK"), Node("e2", "textbox", "Name")])
    pixels = CapturingPixels()
    op = operator(root, a11y, pixels)
    await op.execute({"action": "open", "app": "notepad"})
    raw = await op.execute({"action": "click", "app": "notepad", "ref": "missing"})
    last = _load(raw)
    ok = last["path"] == "a11y" and last["verified"] is False and not pixels.clicks and pixels.annotated == 0
    return ScenarioResult("pixels_skipped_when_a11y_usable", ok, trace=list(op.trace))


async def type_without_app_after_click(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y()
    pixels = CapturingPixels()
    pixels.size = (1920, 1200)
    orig_type = pixels.type_text

    async def type_into_state(text):
        await orig_type(text)
        a11y.document += " " + text

    pixels.type_text = type_into_state
    orig_scroll = pixels.scroll_xy

    async def scroll_into_state(x, y, dy):
        await orig_scroll(x, y, dy)
        a11y.document += " scrolled"

    pixels.scroll_xy = scroll_into_state
    op = operator(root, a11y, pixels)
    skipped = _load(await op.execute({"action": "type", "text": "nope"}))
    await op.execute({"action": "click", "x": 40, "y": 80})
    typed = _load(
        await op.execute(
            {
                "action": "type",
                "text": "https://github.com/nastyrunner13",
                "expect": "github.com",
            }
        )
    )
    keys = _load(await op.execute({"action": "keys", "text": "{ENTER}", "expect": "github.com"}))
    scrolled = _load(await op.execute({"action": "scroll", "dy": -120, "expect": "scrolled"}))
    ok = (
        skipped["verified"] is False
        and "expect" in skipped["verify"]["detail"]
        and typed["path"] == "pixels"
        and typed["verified"] is True
        and pixels.typed == ["https://github.com/nastyrunner13", "{ENTER}"]
        and not a11y.typed
        and keys["verified"] is True
        and scrolled["verified"] is True
        and pixels.scrolls == [(40, 80, -120)]
    )
    return ScenarioResult("type_without_app_after_click", ok, trace=list(op.trace))


async def open_failure_attaches_see(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y()

    async def boom(app, url=None):
        raise RuntimeError("No windows for that process could be found")

    a11y.open = boom
    pixels = CapturingPixels()
    op = operator(root, a11y, pixels)
    last = _load(await op.execute({"action": "open", "app": "notepad"}))
    ok = (
        last["verified"] is False
        and "Do not stop" in last["verify"]["detail"]
        and pixels.shots >= 1
        and not last.get("stuck")
    )
    return ScenarioResult("open_failure_attaches_see", ok, trace=list(op.trace))


async def allowlist_rejects_unknown(root: Path) -> ScenarioResult:
    a11y = ScriptedA11y()
    pixels = CapturingPixels()
    op = operator(root, a11y, pixels)
    raw = await op.execute({"action": "open", "app": "steam"})
    last = _load(raw)
    ok = last["verified"] is False and not a11y.opened and "allowlist" in last["verify"]["detail"]
    return ScenarioResult("allowlist_rejects_unknown", ok, trace=list(op.trace))


async def unknown_app_card_then_grant(root: Path) -> ScenarioResult:
    grants: set[str] = set()
    cfg = perm(root)
    bus = Bus()
    gate = Gate(cfg, bus, session_grants=grants)
    a11y = ScriptedA11y()
    op = Operator(
        cfg,
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
