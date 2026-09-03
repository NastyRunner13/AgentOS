"""Eval scenario functions, grouped by domain."""

from evals.cases.files import file_write_roundtrip, ring2_card_blocks
from evals.cases.memory import memory_recall_after_n, proposals_never_auto_applied
from evals.cases.operator import (
    a11y_click_verified,
    allowlist_rejects_unknown,
    open_failure_attaches_see,
    pixels_skipped_when_a11y_usable,
    pixels_when_a11y_empty,
    stuck_on_broken_verify,
    type_without_app_after_click,
    unknown_app_card_then_grant,
    xy_click_explicit,
)
from evals.cases.research import research_query_cites_fetch

__all__ = [
    "a11y_click_verified",
    "allowlist_rejects_unknown",
    "open_failure_attaches_see",
    "file_write_roundtrip",
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
