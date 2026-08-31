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


DDG_HTML = """
<html><body>
<a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">Example Page</a>
<a class="result__snippet" href="#">A snippet about example.</a>
</body></html>
"""


async def test_web_search_returns_untrusted_titles(monkeypatch):
    import tools.web as webmod

    async def fake_http(method, url, *, data=None, headers=None, timeout=20.0):
        return 200, DDG_HTML, "text/html"

    monkeypatch.setattr(webmod, "_http", fake_http)
    raw = await webmod.search("example", PERM)
    assert "<untrusted" in raw
    assert "Example Page" in raw
    assert "https://example.com/page" in raw


async def test_web_fetch_wraps_body_and_blocks_localhost(monkeypatch):
    import tools.web as webmod

    called = []

    async def fake_http(method, url, *, data=None, headers=None, timeout=20.0):
        called.append(url)
        return 200, "<html><body><p>Hello public.</p></body></html>", "text/html"

    monkeypatch.setattr(webmod, "_http", fake_http)
    blocked = await webmod.fetch("http://127.0.0.1/", PERM)
    assert "blocked" in blocked
    assert "<untrusted" in blocked
    assert called == []

    private = await webmod.fetch("http://192.168.1.1/x", PERM)
    assert "blocked" in private
    assert called == []

    file_url = await webmod.fetch("file:///etc/passwd", PERM)
    assert "blocked" in file_url

    ok = await webmod.fetch("https://example.com/page", PERM)
    assert called == ["https://example.com/page"]
    assert '<untrusted source="web" url="https://example.com/page">' in ok
    assert "Hello public." in ok
    assert "</untrusted>" in ok


async def test_web_tools_dispatch(tmp_path: Path, monkeypatch):
    import tools.web as webmod

    async def fake_search(query, perm_cfg, clip=None):
        return f'<untrusted source="web">\n{query}\n</untrusted>'

    async def fake_fetch(url, perm_cfg, clip=None):
        return f'<untrusted source="web" url="{url}">\nok\n</untrusted>'

    monkeypatch.setattr(webmod, "search", fake_search)
    monkeypatch.setattr(webmod, "fetch", fake_fetch)
    tools = NativeTools(tmp_path, PERM)
    assert "needle" in await tools.execute("web_search", {"query": "needle"})
    assert "ok" in await tools.execute("web_fetch", {"url": "https://example.com"})
