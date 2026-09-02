"""Sandboxed file read/write/move/search/delete inside approved roots."""

from __future__ import annotations

import json
from pathlib import Path


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_plan_path(raw: str, root: Path) -> bool:
    """True only for workspace-root plan.md."""
    if not raw or not root:
        return False
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = root / p
        return p.resolve() == (root.resolve() / "plan.md")
    except OSError:
        return False


def resolve(raw: str, root: Path, perm_cfg: dict) -> Path:
    if not raw:
        raise ValueError("missing path")
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    roots = []
    for r in perm_cfg.get("files", {}).get("approved_roots") or ["."]:
        rp = Path(r).expanduser()
        if not rp.is_absolute():
            rp = root / rp
        roots.append(rp.resolve())
    if not any(_within(p, r) for r in roots):
        raise ValueError(f"path {p} is outside approved roots")
    return p


def size(path: str, root: Path, perm_cfg: dict) -> int:
    try:
        p = resolve(path, root, perm_cfg)
    except ValueError:
        return 0
    return p.stat().st_size if p.exists() and p.is_file() else 0


def run(args: dict, *, root: Path, perm_cfg: dict, clip) -> str:
    action = str(args.get("action", "read"))
    path = str(args.get("path", ""))
    try:
        p = resolve(path, root, perm_cfg)
    except ValueError as exc:
        return str(exc)
    if action == "read":
        if not p.is_file():
            return f"not a file: {p}"
        return clip(p.read_text(encoding="utf-8", errors="replace"))
    if action == "write":
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(args.get("content", "")), encoding="utf-8")
        return f"wrote {p}"
    if action == "move":
        dest = resolve(str(args.get("dest", "")), root, perm_cfg)
        dest.parent.mkdir(parents=True, exist_ok=True)
        p.replace(dest)
        return f"moved {p} -> {dest}"
    if action == "delete":
        if p.is_dir():
            return "refusing to delete a directory"
        try:
            p.unlink()
        except FileNotFoundError:
            return f"missing {p}"
        return f"deleted {p}"
    if action == "search":
        query = str(args.get("query", ""))
        hits = []
        if p.is_file():
            scan = [p]
        else:
            scan = [x for x in p.rglob("*") if x.is_file()]
        for f in scan[:200]:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if query in text or query in f.name:
                hits.append(str(f))
            if len(hits) >= 50:
                break
        return json.dumps(hits)
    return f"unknown files action {action}"
