"""PowerShell runner."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

Runner = Callable[[str, float, Path], Awaitable[str]]


async def powershell(command: str, timeout: float, cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return f"timed out after {timeout}s"
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    code = proc.returncode
    body = out if not err else (out + ("\n" if out else "") + err)
    return body if code == 0 else f"exit {code}\n{body}"


async def run(
    args: dict,
    *,
    runner: Runner,
    perm_cfg: dict,
    root: Path,
    clip,
) -> str:
    command = str(args.get("command", "")).strip()
    if not command:
        return "empty command"
    timeout = float(args.get("timeout_seconds") or perm_cfg.get("shell", {}).get("timeout_seconds", 60))
    cwd_raw = perm_cfg.get("shell", {}).get("working_directory", ".")
    cwd = Path(cwd_raw)
    if not cwd.is_absolute():
        cwd = (root / cwd).resolve()
    return clip(await runner(command, timeout, cwd))
