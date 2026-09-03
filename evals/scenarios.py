"""Repeatable Phase 2 suite. Fakes, not a live desktop — same operator code path."""

from __future__ import annotations

from pathlib import Path

from evals.cases import (
    a11y_click_verified,
    allowlist_rejects_unknown,
    file_write_roundtrip,
    memory_recall_after_n,
    open_failure_attaches_see,
    pixels_skipped_when_a11y_usable,
    pixels_when_a11y_empty,
    proposals_never_auto_applied,
    research_query_cites_fetch,
    ring2_card_blocks,
    stuck_on_broken_verify,
    type_without_app_after_click,
    unknown_app_card_then_grant,
    xy_click_explicit,
)
from evals.fakes import CapturingPixels, ScriptedA11y, operator as _operator, perm as _perm

__all__ = [
    "CapturingPixels",
    "ScriptedA11y",
    "_operator",
    "_perm",
    "a11y_click_verified",
    "allowlist_rejects_unknown",
    "default_suite",
    "file_write_roundtrip",
    "open_failure_attaches_see",
    "memory_recall_after_n",
    "pixels_skipped_when_a11y_usable",
    "pixels_when_a11y_empty",
    "proposals_never_auto_applied",
    "research_query_cites_fetch",
    "ring2_card_blocks",
    "stuck_on_broken_verify",
    "type_without_app_after_click",
    "unknown_app_card_then_grant",
    "xy_click_explicit",
]


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
        bind(xy_click_explicit, "xy_click_explicit"),
        bind(stuck_on_broken_verify, "stuck_on_broken_verify"),
        bind(pixels_skipped_when_a11y_usable, "pixels_skipped_when_a11y_usable"),
        bind(type_without_app_after_click, "type_without_app_after_click"),
        bind(open_failure_attaches_see, "open_failure_attaches_see"),
        bind(allowlist_rejects_unknown, "allowlist_rejects_unknown"),
        bind(unknown_app_card_then_grant, "unknown_app_card_then_grant"),
        bind(file_write_roundtrip, "file_write_roundtrip"),
        bind(ring2_card_blocks, "ring2_card_blocks"),
        bind(memory_recall_after_n, "memory_recall_after_n"),
        bind(proposals_never_auto_applied, "proposals_never_auto_applied"),
        bind(research_query_cites_fetch, "research_query_cites_fetch"),
    ]
