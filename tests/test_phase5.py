"""Phase 5 slice 1: orb is a bus subscriber, never a mic owner."""

from __future__ import annotations

import ast
from pathlib import Path

from orb.draw import render_frame
from orb.overlay import parse_tk_origin
from orb.presence import Presence
from orb.shader import agent_state

ROOT = Path(__file__).resolve().parents[1]
SIZE = 140


def test_orb_does_not_own_mic_or_master():
    for path in (ROOT / "orb").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "sounddevice" not in src, path.name
        assert "pyaudio" not in src, path.name
        name = str(path.relative_to(ROOT)).replace("\\", "/")
        tree = ast.parse(src, filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("brain"), name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("brain"), name
                assert not node.module.startswith("voice"), name


def test_b_phases_from_bus_events():
    p = Presence()
    p.on_state({"phase": "listening"})
    assert p.phase == "listening"
    p.on_state({"phase": "thinking"})
    p.on_state({"phase": "token", "text": "hi"})
    assert p.phase == "thinking"
    p.on_state({"phase": "idle"})
    p.on_tts({"rms": 0.4, "t": 0})
    assert p.phase == "speaking"
    assert p.rms == 0.4
    p.on_tts({"rms": 0.0, "t": 1})
    p.on_state({"phase": "idle"})
    assert p.phase == "idle"
    p.on_state({"phase": "stuck"})
    assert p.phase == "stuck"


def test_card_amber_until_resolved():
    p = Presence()
    p.on_card({"id": "a"})
    assert p.card is True
    p.on_card({"id": "b"})
    p.on_resolved({"id": "a"})
    assert p.card is True
    p.on_resolved({"id": "b"})
    assert p.card is False


def test_listening_follows_mic_amplitude():
    p = Presence()
    p.on_state({"phase": "idle"})
    p.on_mic({"rms": 0.2, "t": 0})
    assert p.phase == "listening"
    assert p.mic_rms == 0.2


def test_presence_maps_elevenlabs_agent_state():
    p = Presence()
    assert p.snapshot()["agent_state"] is None
    p.on_state({"phase": "listening"})
    assert p.snapshot()["agent_state"] == "listening"
    p.on_state({"phase": "thinking"})
    assert p.snapshot()["agent_state"] == "thinking"
    p.on_state({"phase": "speaking"})
    assert agent_state(p.phase) == "talking"
    p.on_state({"phase": "waking"})
    assert agent_state("waking") == "listening"
    p.on_state({"phase": "stuck"})
    assert agent_state("stuck") == "thinking"


def test_orb_html_ships_elevenlabs_states():
    html = (ROOT / "orb" / "orb.html").read_text(encoding="utf-8")
    assert "setOrb" in html
    assert "listening" in html
    assert "talking" in html
    assert "thinking" in html
    assert "ui.elevenlabs.io/docs/components/orb" in html


def test_draw_all_phases_render():
    for phase in ("idle", "waking", "listening", "thinking", "speaking", "stuck"):
        img = render_frame(phase=phase, rms=0.3, mic_rms=0.2, card=False, size=SIZE, t=1.0)
        assert img.size == (SIZE, SIZE)


def test_draw_center_opaque_corners_clear():
    img = render_frame(phase="idle", size=SIZE, t=1.0)
    px = img.getpixel((SIZE // 2, SIZE // 2))
    assert px[3] > 200
    corner = img.getpixel((0, 0))
    assert corner[3] == 0


def test_draw_card_tints_orb_amber():
    plain = render_frame(phase="idle", card=False, size=SIZE, t=1.0)
    tinted = render_frame(phase="idle", card=True, size=SIZE, t=1.0)

    def red_minus_blue(img):
        total = 0
        n = 0
        for x in range(0, SIZE, 8):
            for y in range(0, SIZE, 8):
                r, _g, b, a = img.getpixel((x, y))
                if a > 200:
                    total += r - b
                    n += 1
        return total / max(n, 1)

    assert red_minus_blue(tinted) > red_minus_blue(plain)


def test_draw_muted_marks_the_orb():
    live = render_frame(phase="idle", size=SIZE, muted=False, t=1.0)
    mute = render_frame(phase="idle", size=SIZE, muted=True, t=1.0)
    assert live.tobytes() != mute.tobytes()


def test_draw_listening_differs_from_idle():
    idle = render_frame(phase="idle", size=SIZE, t=1.0)
    live = render_frame(phase="listening", mic_rms=0.4, size=SIZE, t=1.0)
    assert live.tobytes() != idle.tobytes()


def test_draw_talking_differs_from_listening():
    listen = render_frame(phase="listening", mic_rms=0.4, size=SIZE, t=1.0)
    speak = render_frame(phase="speaking", rms=0.4, size=SIZE, t=1.0)
    assert listen.tobytes() != speak.tobytes()


def test_draw_thinking_differs_from_idle():
    idle = render_frame(phase="idle", size=SIZE, t=1.0)
    think = render_frame(phase="thinking", size=SIZE, t=1.0)
    assert idle.tobytes() != think.tobytes()


def test_parse_tk_origin_handles_signed_coords():
    assert parse_tk_origin("320x56+12+40") == (12, 40)
    assert parse_tk_origin("320x56+12-40") == (12, -40)
    assert parse_tk_origin("320x56-12+40") == (-12, 40)
    assert parse_tk_origin("320x56+-8-12") == (-8, -12)


def test_overlay_does_not_start_webview():
    src = (ROOT / "orb" / "overlay.py").read_text(encoding="utf-8")
    assert "webview" not in src
    assert "_tk_loop" in src
