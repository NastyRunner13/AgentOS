"""ElevenLabs Orb frames for the overlay. No window, no mic."""

from __future__ import annotations

from PIL import Image

from orb.shader import agent_state, palette, render


def render_frame(
    *,
    phase: str = "idle",
    rms: float = 0.0,
    mic_rms: float = 0.0,
    card: bool = False,
    muted: bool = False,
    width: int | None = None,
    height: int | None = None,
    size: int = 140,
    t: float = 1.0,
    wave=None,
) -> Image.Image:
    if width is not None or height is not None:
        size = min(int(width or size), int(height or size))
    size = max(32, int(size))
    # SYNC: card-tint — Presence.card paints the orb amber
    colors = palette(phase=phase, card=card, muted=muted)
    return render(
        size,
        agent=agent_state(phase),
        t=t,
        mic_rms=mic_rms,
        rms=rms,
        colors=colors,
    )
