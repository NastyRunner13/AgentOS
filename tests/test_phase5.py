"""Phase 5 slice 1: voice bar is a bus subscriber, never a mic owner."""

from __future__ import annotations

import ast
from pathlib import Path

from orb.draw import render_frame
from orb.overlay import parse_tk_origin
from orb.presence import Presence

ROOT = Path(__file__).resolve().parents[1]


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


def test_draw_all_phases_render():
    for phase in ("idle", "waking", "listening", "thinking", "speaking", "stuck"):
        img = render_frame(phase=phase, rms=0.3, mic_rms=0.2, card=False, width=200, height=40, t=1.0)
        assert img.size == (200, 40)


def test_draw_button_is_opaque_corners_clear():
    img = render_frame(phase="idle", width=320, height=56)
    r = (56 - 16) / 2
    cx = int(2 + 8 + r)
    cy = 28
    px = img.getpixel((cx, cy))
    assert px[3] > 200
    corner = img.getpixel((0, 0))
    assert corner[3] == 0


def test_draw_card_tints_button_amber():
    img = render_frame(phase="idle", card=True, width=320, height=56)
    r = (56 - 16) / 2
    cx = int(2 + 8 + r)
    px = img.getpixel((cx - int(r) + 3, 28))
    assert px[0] > px[2]


def test_draw_muted_marks_the_button():
    live = render_frame(phase="idle", width=320, height=56, muted=False)
    mute = render_frame(phase="idle", width=320, height=56, muted=True)
    assert live.tobytes() != mute.tobytes()


def test_draw_listening_waveform_moves():
    idle = render_frame(phase="idle", width=320, height=56, wave=[0.05] * 36)
    live = render_frame(phase="listening", mic_rms=0.4, width=320, height=56, wave=[0.7] * 36)
    assert live.tobytes() != idle.tobytes()
    # waveform lives to the right of the mic button
    idle_px = idle.getpixel((180, 28))
    live_px = live.getpixel((180, 28))
    assert live_px[3] >= idle_px[3]


def test_draw_speaking_waveform_differs_from_listening():
    listen = render_frame(phase="listening", mic_rms=0.4, width=320, height=56, wave=[0.6] * 36)
    speak = render_frame(phase="speaking", rms=0.4, width=320, height=56, wave=[0.6] * 36)
    assert listen.tobytes() != speak.tobytes()


def test_parse_tk_origin_handles_signed_coords():
    assert parse_tk_origin("320x56+12+40") == (12, 40)
    assert parse_tk_origin("320x56+12-40") == (12, -40)
    assert parse_tk_origin("320x56-12+40") == (-12, 40)
    assert parse_tk_origin("320x56+-8-12") == (-8, -12)
