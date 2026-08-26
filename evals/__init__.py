"""Eval harness v1. `python main.py --eval` writes metrics JSON under evals/runs/."""

from evals.harness import run_suite

__all__ = ["run_suite"]
