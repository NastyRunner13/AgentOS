"""Tests for extended browser actions and operator perception tools."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from kernel import Bus
from memory import Episodic
from tools import NativeTools
from tools.browser import Browser
from tools.operator import Operator


PERM = {
    "files": {"approved_roots": ["."]},
    "shell": {"allowlist": ["echo"]},
    "browser": {"headless": True},
    "operator": {
        "allowlist": {
            "notepad": {"exe": "notepad.exe"},
            "browser": {"kind": "playwright"},
        }
    },
}


class FakePage:
    def __init__(self):
        self.url = "https://example.com/test"
        self.uploaded = []
        self.waited = []

    def locator(self, sel):
        page_self = self

        class Loc:
            @property
            def first(self):
                return self

            async def set_input_files(self, path):
                page_self.uploaded.append(path)

            async def wait_for(self, timeout=None):
                page_self.waited.append(sel)

            async def click(self):
                pass

            async def fill(self, text):
                pass

            async def inner_text(self):
                return "hello"

        return Loc()

    async def wait_for_load_state(self, state, timeout=None):
        self.waited.append(state)

    async def screenshot(self, path=None):
        return b"fake_png_data"


async def test_browser_upload_and_wait(tmp_path: Path):
    b = Browser(PERM)
    b._page = FakePage()

    dummy_file = tmp_path / "avatar.png"
    dummy_file.write_bytes(b"avatar-bytes")

    # Missing path
    res_err = await b.run({"action": "upload", "path": ""})
    assert "missing path" in res_err

    # File not found
    res_nf = await b.run({"action": "upload", "path": str(tmp_path / "not_found.png")})
    assert "not found" in res_nf

    # Successful upload
    res_ok = await b.run({"action": "upload", "ref": "#file-input", "path": str(dummy_file)})
    assert "uploaded avatar.png" in res_ok
    assert str(dummy_file) in b._page.uploaded

    # Wait action with selector
    res_wait = await b.run({"action": "wait", "ref": "#submit-btn", "timeout": 5})
    assert "waited for #submit-btn" in res_wait

    # Wait action for network
    res_net = await b.run({"action": "wait", "timeout": 5})
    assert "waited for networkidle" in res_net

    # Screenshot action
    shot_path = tmp_path / "shot.png"
    res_shot = await b.run({"action": "screenshot", "path": str(shot_path)})
    assert f"screenshot saved to {shot_path}" in res_shot


async def test_operator_see_and_focus(tmp_path: Path):
    bus = Bus()
    memory = Episodic(tmp_path / "events.db")

    class FakePixels:
        async def screenshot(self):
            return b"fake_desktop_png"

    class FakeRegistry:
        async def complete(self, role, messages, **kwargs):
            return "Active window is VS Code with open file main.py.", []

    op = Operator(
        PERM,
        bus,
        memory,
        tmp_path,
        pixels=FakePixels(),
        registry=FakeRegistry(),
    )

    # Test "see" (screen visual perception)
    res_see_raw = await op.execute({"action": "see", "query": "what is on screen?"})
    res_see = json.loads(res_see_raw)
    assert res_see["verified"] is True
    assert res_see["action"] == "see"
    assert "VS Code" in res_see["observation"]
    assert "<untrusted source=\"screen_vision\">" in res_see["observation"]

    # Test "list_windows"
    res_wins_raw = await op.execute({"action": "list_windows"})
    res_wins = json.loads(res_wins_raw)
    assert "windows" in res_wins or "verify" in res_wins
