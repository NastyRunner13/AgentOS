"""Boot the kernel. `python main.py --cli` is the Phase 1 surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from boot import ROOT, collect_secrets  # re-exported for `from main import collect_secrets`
from ui.cli import run_cli

__all__ = ["ROOT", "collect_secrets", "main"]


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS")
    parser.add_argument("--cli", action="store_true", help="interactive chat loop")
    parser.add_argument(
        "--voice",
        action="store_true",
        help="start VoiceIO and the voice orb (click / /listen / hotkey)",
    )
    parser.add_argument("--eval", action="store_true", help="run the Phase 2 eval suite")
    parser.add_argument("--root", default=str(ROOT), help="repo root (configs live in <root>/config)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.eval:
        from evals.harness import run_suite

        path = asyncio.run(run_suite(root))
        summary = json.loads(path.read_text(encoding="utf-8"))
        print(path)
        print(
            f"success_pct={summary['success_pct']} latency_ms={summary['latency_ms']} "
            f"token_cost={summary['token_cost']} human_interventions={summary['human_interventions']} "
            f"cost_per_accepted_outcome={summary['cost_per_accepted_outcome']}"
        )
        return
    if args.cli:
        asyncio.run(run_cli(root, voice_flag=args.voice))
        return
    parser.print_help()
    print("\nPhase 1 surface is the CLI: python main.py --cli")
    print("Phase 2 eval suite: python main.py --eval")


if __name__ == "__main__":
    main()
