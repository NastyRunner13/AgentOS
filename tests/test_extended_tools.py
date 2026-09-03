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


async def test_operator_type_keys_scroll_without_app_use_pixels(tmp_path: Path):
    """Live Brave trace: after a taskbar click, type without x,y was
    rejected as '' not on the operator allowlist, then the model stopped.
    """
    a11y = ScriptedA11y()
    pixels = CapturingPixels()
    pixels.size = (1920, 1200)
    orig_type = pixels.type_text

    async def type_into_state(text):
        await orig_type(text)
        a11y.document += " " + text

    pixels.type_text = type_into_state
    orig_scroll = pixels.scroll_xy

    async def scroll_into_state(x, y, dy):
        await orig_scroll(x, y, dy)
        a11y.document += " scrolled"

    pixels.scroll_xy = scroll_into_state
    op = _operator(tmp_path, a11y, pixels)
    clicked = json.loads(await op.execute({"action": "click", "x": 40, "y": 80}))
    assert clicked["verified"] is True
    typed = json.loads(
        await op.execute(
            {
                "action": "type",
                "text": "https://github.com/nastyrunner13",
                "expect": "github.com",
            }
        )
    )
    assert typed["verified"] is True
    assert typed["path"] == "pixels"
    assert pixels.typed == ["https://github.com/nastyrunner13"]
    assert a11y.typed == []
    keys = json.loads(await op.execute({"action": "keys", "text": "{ENTER}", "expect": "github.com"}))
    assert keys["verified"] is True
    assert pixels.typed[-1] == "{ENTER}"
    scrolled = json.loads(await op.execute({"action": "scroll", "dy": -120, "expect": "scrolled"}))
    assert scrolled["verified"] is True
    assert pixels.scrolls == [(40, 80, -120)]


async def test_focus_act_requires_expect_and_prior_click(tmp_path: Path):
    pixels = CapturingPixels()
    pixels.size = (1920, 1200)
    op = _operator(tmp_path, ScriptedA11y(), pixels)
    no_expect = json.loads(await op.execute({"action": "type", "text": "secret"}))
    assert no_expect["verified"] is False
    assert pixels.typed == []
    assert "expect" in no_expect["verify"]["detail"]
    no_click = json.loads(
        await op.execute({"action": "type", "text": "secret", "expect": "secret"})
    )
    assert no_click["verified"] is False
    assert pixels.typed == []
    assert "prior click" in no_click["verify"]["detail"]
    center = json.loads(
        await op.execute({"action": "scroll", "dy": -120, "expect": "x"})
    )
    assert center["verified"] is False
    assert pixels.scrolls == []
    await op.execute({"action": "click", "x": 40, "y": 80})
    miss = json.loads(
        await op.execute({"action": "type", "text": "secret", "expect": "not-on-screen"})
    )
    assert pixels.typed == ["secret"]
    assert miss["verified"] is False
    assert miss.get("stuck") is False


async def test_open_failure_attaches_screen_and_does_not_stop(tmp_path: Path):
    a11y = ScriptedA11y()

    async def boom(app, url=None):
        raise RuntimeError("No windows for that process could be found")

    a11y.open = boom
    pixels = CapturingPixels()
    op = _operator(tmp_path, a11y, pixels)
    raw = json.loads(await op.execute({"action": "open", "app": "notepad"}))
    assert raw["verified"] is False
    assert raw.get("stuck") is False
    assert "Do not stop" in raw["verify"]["detail"]
    assert pixels.shots >= 1
    assert raw.get("screenshot") or raw["verify"]["detail"]


async def test_click_without_xy_or_app_explains_coords(tmp_path: Path):
    op = _operator(tmp_path, ScriptedA11y(), CapturingPixels())
    raw = json.loads(await op.execute({"action": "click"}))
    assert raw["verified"] is False
    assert "x,y" in raw["verify"]["detail"]


def test_resolve_exe_prefers_existing_path(tmp_path: Path, monkeypatch):
    from tools.a11y import resolve_exe

    exe = tmp_path / "brave.exe"
    exe.write_bytes(b"x")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # KNOWN_EXES brave includes %LOCALAPPDATA%\BraveSoftware\... which will miss;
    # spec path that exists wins.
    assert resolve_exe("brave", {"exe": str(exe)}) == str(exe)
    missing = resolve_exe("not-an-app", {"exe": "missing-bin.exe"})
    assert missing.endswith("missing-bin.exe")


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


async def test_browser_auto_recovery_when_closed():
    class MockClosedPage:
        def __init__(self):
            self.closed = True

        def is_closed(self):
            return self.closed

        async def goto(self, url):
            raise Exception("Page.goto: Target page, context or browser has been closed")

    b = Browser(PERM)
    b._page = MockClosedPage()
    assert b._is_alive() is False

    reopened = False

    async def mock_init():
        nonlocal reopened
        reopened = True
        b._page = FakePage()
        return None

    b._init_session = mock_init
    res = await b.run({"action": "snapshot"})
    assert reopened is True
    assert "hello" in res
