"""Tests for extended browser actions and operator perception tools."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from kernel import Bus
from memory import Episodic
from tools import NativeTools
from tools.browser import Browser
from evals.scenarios import CapturingPixels, ScriptedA11y, _operator
from tools.operator import Operator
from tools.pixels import LivePixels


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


async def test_operator_xy_click_and_scroll(tmp_path: Path):
    a11y = ScriptedA11y()
    pixels = CapturingPixels()
    op = _operator(tmp_path, a11y, pixels)
    clicked = json.loads(await op.execute({"action": "click", "x": 40, "y": 80}))
    assert clicked["path"] == "pixels"
    assert clicked["verified"] is True
    assert pixels.clicks == [(40, 80)]
    assert a11y.clicks == []
    scrolled = json.loads(await op.execute({"action": "scroll", "x": 40, "y": 80, "dy": -120}))
    assert scrolled["verified"] is True
    assert pixels.scrolls == [(40, 80, -120)]
    denied = json.loads(await op.execute({"action": "click", "app": "steam", "ref": "e1"}))
    assert denied["verified"] is False
    assert "allowlist" in denied["verify"]["detail"]


def test_pixels_from_image_scales_and_keeps_origin_for_click():
    px = LivePixels(Path("."))
    px.size = (1920, 1080)
    px.image_size = (1280, 720)
    px.origin = (0, 0)
    assert px.from_image(500, 500) == (960, 540)
    px.size = (800, 600)
    px.image_size = (800, 600)
    assert px.from_image(10, 20) == (8, 12)


def test_pixels_from_image_zero_to_1000_is_the_click_space():
    """Gemini emits 0-1000. Image-pixel scale of those numbers misses the taskbar.

    Live session: 1920x1200 monitor, 1280x800 attached shot. The model named
    Notion at 0-1000 (534, 974), then 'corrected' y to 743 image pixels.
    """
    px = LivePixels(Path("."))
    px.size = (1920, 1200)
    px.image_size = (1280, 800)
    px.origin = (0, 0)
    assert px.from_image(534, 974) == (1025, 1169)
    assert px.from_image(514, 972) == (987, 1166)
    assert px.from_image(538, 973) == (1033, 1168)
    # 743 as 0-1000 is mid-window, not the taskbar — still not image*1.5.
    assert px.from_image(534, 743) == (1025, 892)
    assert px.from_image(1280, 800) == (1919, 1199)


def test_downscale_draws_0_1000_axes_without_changing_size(tmp_path: Path):
    from io import BytesIO
    from PIL import Image

    im = Image.new("RGB", (1920, 1200), (10, 10, 10))
    buf = BytesIO()
    im.save(buf, format="PNG")
    px = LivePixels(tmp_path)
    out = Image.open(BytesIO(px._downscale(buf.getvalue())))
    assert out.size == (1280, 800)
    assert px.image_size == (1280, 800)


async def test_xy_click_rejects_coords_still_outside_screen(tmp_path: Path):
    pixels = CapturingPixels()
    pixels.size = (1920, 1200)
    pixels.image_size = (1280, 800)

    def from_image(x, y):
        return int(x), int(y)

    pixels.from_image = from_image
    op = _operator(tmp_path, ScriptedA11y(), pixels)
    raw = json.loads(await op.execute({"action": "click", "x": 2000, "y": 2000}))
    assert raw["verified"] is False
    assert pixels.clicks == []
    assert "outside" in raw["verify"]["detail"]
