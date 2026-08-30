"""Workspace chrome: display path and git branch for the CLI header."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_branch_cache: dict[str, tuple[float, str]] = {}
_BRANCH_TTL = 5.0


def display_cwd(root: Path) -> str:
    try:
        resolved = Path(root).expanduser().resolve()
    except OSError:
        resolved = Path(root)
    try:
        rel = resolved.relative_to(Path.home())
        text = rel.as_posix()
        return "~" if text in ("", ".") else f"~/{text}"
    except ValueError:
        return resolved.as_posix()


def git_branch(root: Path) -> str:
    key = str(root)
    now = time.monotonic()
    hit = _branch_cache.get(key)
    if hit and now - hit[0] < _BRANCH_TTL:
        return hit[1]
    name = _probe_branch(root)
    _branch_cache[key] = (now, name)
    return name


def _probe_branch(root: Path) -> str:
    kwargs = {
        "cwd": str(root),
        "capture_output": True,
        "text": True,
        "timeout": 1.5,
    }
    if _CREATE_NO_WINDOW:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        proc = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    name = (proc.stdout or "").strip()
    if name != "HEAD":
        return name
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return "detached"
    sha = (proc.stdout or "").strip()
    return f"detached {sha}" if sha else "detached"
