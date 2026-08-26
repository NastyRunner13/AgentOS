from __future__ import annotations

import asyncio
from pathlib import Path

from evals.harness import run_suite


def main() -> None:
    path = asyncio.run(run_suite(Path.cwd()))
    print(path)


if __name__ == "__main__":
    main()
