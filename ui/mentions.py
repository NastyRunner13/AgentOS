"""@path file mentions from the workspace (cwd / --root)."""

from __future__ import annotations

import os
import re
from pathlib import Path

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "data",
    ".mypy_cache",
    ".pytest_cache",
    ".eggs",
    ".idea",
    ".vs",
}
_SKIP_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp4",
    ".zip",
    ".7z",
    ".db",
    ".sqlite",
    ".bin",
    ".pdf",
}
_MENTION = re.compile(r"(?<!\S)@([^\s@]+)")
_ATTACHED = re.compile(r"\n*<attached path=\"[^\"]+\">.*?</attached>\s*", re.S)
_TRAIL_PUNCT = ",;:!?)"
_MAX_ATTACH = 6


def mention_query(text_before_cursor: str) -> str | None:
    """Prefix after a live `@` mention, or None if the cursor is not in one."""
    i = text_before_cursor.rfind("@")
    if i < 0:
        return None
    if i > 0 and not text_before_cursor[i - 1].isspace():
        return None
    rest = text_before_cursor[i + 1 :]
    if any(c.isspace() for c in rest):
        return None
    return rest


def _skip_file(name: str) -> bool:
    lower = name.lower()
    if lower == ".env":
        return True
    suffix = Path(name).suffix.lower()
    return suffix in _SKIP_SUFFIXES


def list_workspace_paths(root: Path, *, limit: int = 500) -> list[tuple[str, bool]]:
    """Relative posix paths under root. Dirs have a trailing slash and is_dir True."""
    try:
        root = root.resolve()
    except OSError:
        return []
    if not root.is_dir():
        return []
    out: list[tuple[str, bool]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".") and not d.endswith(".egg-info")
        ]
        dirnames.sort()
        rel_dir = Path(dirpath).resolve().relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            out.append((rel + "/", True))
            if len(out) >= limit:
                return out
        for name in sorted(filenames):
            if _skip_file(name):
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            out.append((rel, False))
            if len(out) >= limit:
                return out
    return out


def _clean_token(token: str) -> str:
    token = token.replace("\\", "/")
    while token.startswith("./"):
        token = token[2:]
    while token and token[-1] in _TRAIL_PUNCT:
        stem = token.lower()
        if stem.endswith((".md", ".py", ".yaml", ".yml", ".json", ".txt", ".toml")):
            break
        token = token[:-1]
    return token


def strip_attachments(content: str) -> str:
    return _ATTACHED.sub("", content).rstrip()


def expand_mentions(text: str, root: Path, *, max_chars: int = 8000) -> str:
    """Append <attached> blocks for each @path in text. Unchanged if none match."""
    seen: list[str] = []
    for match in _MENTION.finditer(text):
        rel = _clean_token(match.group(1))
        if not rel or rel in seen:
            continue
        seen.append(rel)
        if len(seen) >= _MAX_ATTACH:
            break
    if not seen:
        return text
    try:
        root = root.resolve()
    except OSError:
        return text
    chunks = [text.rstrip()]
    for rel in seen:
        chunks.append(_read_attach(root, rel, max_chars))
    return "\n".join(chunks)


def _read_attach(root: Path, rel: str, max_chars: int) -> str:
    target = (root / rel).resolve()
    if Path(rel).name.lower() == ".env":
        return f'<attached path="{rel}">\nskipped secret file\n</attached>'
    try:
        target.relative_to(root)
    except ValueError:
        return f'<attached path="{rel}">\noutside workspace\n</attached>'
    if not target.exists():
        return f'<attached path="{rel}">\nmissing file\n</attached>'
    if target.is_dir():
        names = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())[:40]
        listing = "\n".join(names) if names else "(empty)"
        return f'<attached path="{rel}">\ndirectory\n{listing}\n</attached>'
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return f'<attached path="{rel}">\n{exc}\n</attached>'
    if b"\x00" in raw[:2048]:
        return f'<attached path="{rel}">\nbinary file not attached\n</attached>'
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n… truncated ({len(text)} chars)"
    return f'<attached path="{rel}">\n{text}\n</attached>'
