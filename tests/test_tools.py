"""Files sandbox and native tool dispatch."""

from __future__ import annotations

from pathlib import Path

from tools import NativeTools

PERM = {
    "files": {
        "approved_roots": ["."],
        "read_ring": 0,
        "write_ring": 1,
        "delete_ring": 2,
        "delete_size_threshold_bytes": 1048576,
        "delete_over_threshold_ring": 3,
    },
    "shell": {"allowlist": ["echo"], "timeout_seconds": 5, "working_directory": "."},
    "browser": {"headless": True},
}


def test_files_roundtrip_search_move(tmp_path: Path):
    tools = NativeTools(tmp_path, PERM)
    assert "wrote" in tools.files({"action": "write", "path": "a.txt", "content": "hello"})
    assert tools.files({"action": "read", "path": "a.txt"}) == "hello"
    assert "a.txt" in tools.files({"action": "search", "path": ".", "query": "hello"})
    assert "moved" in tools.files({"action": "move", "path": "a.txt", "dest": "sub/b.txt"})
    assert "hello" in tools.files({"action": "read", "path": "sub/b.txt"})


def test_files_refuse_outside_roots(tmp_path: Path):
    tools = NativeTools(tmp_path, PERM)
    outside = tmp_path.parent / "nope.txt"
    msg = tools.files({"action": "write", "path": str(outside), "content": "x"})
    assert "outside approved roots" in msg
    assert not outside.exists()


def test_files_refuse_directory_delete_and_missing(tmp_path: Path):
    tools = NativeTools(tmp_path, PERM)
    (tmp_path / "d").mkdir()
    assert "refusing" in tools.files({"action": "delete", "path": "d"})
    assert "missing" in tools.files({"action": "delete", "path": "nope.txt"})


def test_files_missing_path():
    tools = NativeTools(Path("."), PERM)
    assert "missing path" in tools.files({"action": "read", "path": ""})


async def test_empty_shell_and_unknown_tool(tmp_path: Path):
    tools = NativeTools(tmp_path, PERM)
    assert await tools.shell({"command": "  "}) == "empty command"
    assert "unknown tool" in await tools.execute("nope", {})
    assert await tools.execute("computer", {}) == "operator not configured"


def test_file_size(tmp_path: Path):
    tools = NativeTools(tmp_path, PERM)
    (tmp_path / "a.txt").write_text("abcd", encoding="utf-8")
    assert tools.file_size("a.txt") == 4
    assert tools.file_size("missing.txt") == 0
    assert tools.file_size("") == 0
