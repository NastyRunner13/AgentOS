"""PIL frames for the bottom-center voice bar. No window, no mic."""

from __future__ import annotations

import math

from PIL import Image, ImageDraw

BAR_BG = (18, 20, 24, 250)
IDLE_BTN = (38, 42, 50, 255)
WAVE_IDLE = (70, 76, 86, 180)

PHASE_BTN = {
    "idle": IDLE_BTN,
    "waking": (28, 110, 128, 255),
    "listening": (16, 150, 170, 255),
    "thinking": (78, 62, 150, 255),
    "speaking": (18, 130, 110, 255),
    "stuck": (160, 48, 58, 255),
    "hidden": IDLE_BTN,
}
PHASE_WAVE = {
    "idle": WAVE_IDLE,
    "waking": (120, 220, 235, 220),
    "listening": (90, 230, 245, 240),
    "thinking": (180, 170, 255, 210),
    "speaking": (140, 245, 210, 240),
    "stuck": (255, 110, 120, 230),
    "hidden": WAVE_IDLE,
}
AMBER_BTN = (220, 160, 48, 255)
AMBER_WAVE = (255, 196, 72, 230)


def render_frame(
    *,
    phase: str = "idle",
    rms: float = 0.0,
    mic_rms: float = 0.0,
    card: bool = False,
    muted: bool = False,
    width: int = 320,
    height: int = 56,
    t: float = 0.0,
    wave: tuple[float, ...] | list[float] | None = None,
) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    pad = 2
    bar = (pad, pad, width - pad - 1, height - pad - 1)
    draw.rounded_rectangle(bar, radius=(height - 2 * pad) // 2, fill=BAR_BG)

    cy = height / 2
    btn_r = (height - 16) / 2
    btn_cx = pad + 8 + btn_r
    # SYNC: card-tint — Presence.card paints the mic button amber
    btn_fill = AMBER_BTN if card and phase != "stuck" else PHASE_BTN.get(phase, IDLE_BTN)
    if muted:
        btn_fill = (48, 50, 56, 255)
    _mic_button(draw, btn_cx, cy, btn_r, btn_fill, muted)

    samples = list(wave) if wave is not None else _synth_wave(phase, rms, mic_rms, t)
    wx0 = btn_cx + btn_r + 10
    wx1 = width - pad - 14
    wy0 = pad + 10
    wy1 = height - pad - 10
    color = AMBER_WAVE if card and phase != "stuck" else PHASE_WAVE.get(phase, WAVE_IDLE)
    _waveform(draw, (wx0, wy0, wx1, wy1), samples, color, t, phase)
    return canvas


def _synth_wave(phase: str, rms: float, mic_rms: float, t: float, n: int = 36) -> list[float]:
    if phase == "listening":
        level = min(1.0, max(0.08, mic_rms * 4))
    elif phase == "speaking":
        level = min(1.0, max(0.08, rms * 4))
    elif phase == "thinking":
        return [max(0.06, 0.18 + 0.38 * max(0.0, math.sin(t * 5.2 - i * 0.32))) for i in range(n)]
    elif phase == "waking":
        level = 0.25 + 0.2 * abs(math.sin(t * 8))
    else:
        return [0.05] * n
    return [level * (0.45 + 0.55 * abs(math.sin(i * 0.7 + t * 9))) for i in range(n)]


def _mic_button(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill, muted: bool) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    icon = (245, 248, 250, 255) if not muted else (160, 164, 172, 255)
    w = max(2, int(r * 0.12))
    mw = r * 0.22
    head_top = cy - r * 0.40
    head_bot = cy + r * 0.08
    draw.rounded_rectangle((cx - mw, head_top, cx + mw, head_bot), radius=mw, fill=icon)
    draw.arc(
        (cx - mw - 5, cy - r * 0.18, cx + mw + 5, cy + r * 0.36),
        start=15,
        end=165,
        fill=icon,
        width=w,
    )
    yoke_b = cy + r * 0.36
    draw.line((cx, yoke_b, cx, yoke_b + r * 0.16), fill=icon, width=w)
    base_y = yoke_b + r * 0.16
    draw.line((cx - r * 0.20, base_y, cx + r * 0.20, base_y), fill=icon, width=w)
    if muted:
        draw.line(
            (cx - r * 0.55, cy + r * 0.5, cx + r * 0.55, cy - r * 0.5),
            fill=(255, 255, 255, 230),
            width=max(2, int(r * 0.16)),
        )


def _waveform(
    draw: ImageDraw.ImageDraw,
    box: tuple[float, float, float, float],
    samples: list[float],
    color: tuple,
    t: float,
    phase: str,
) -> None:
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    if w <= 8 or h <= 4 or not samples:
        return
    cy = (y0 + y1) / 2
    n = len(samples)
    gap = 1.0
    bar_w = max(2.0, (w / n) - gap)
    for i, s in enumerate(samples):
        live = max(0.0, min(1.0, s))
        if phase in ("listening", "speaking") and live > 0.04:
            live *= 0.5 + 0.5 * abs(math.sin(i * 0.85 + t * 10))
        bh = max(1.5, live * (h * 0.48))
        x = x0 + i * (w / n)
        draw.rounded_rectangle(
            (x, cy - bh, x + bar_w, cy + bh),
            radius=min(bar_w / 2, bh),
            fill=color,
        )
