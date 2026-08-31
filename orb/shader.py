"""ElevenLabs UI Orb shader — idle / listening / thinking / talking.

Source: https://ui.elevenlabs.io/docs/components/orb
https://github.com/elevenlabs/ui/blob/main/apps/www/registry/elevenlabs-ui/ui/orb.tsx
MIT.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

PI = math.pi
SEED = 1000
DEFAULT = ("#CADCFC", "#A0B9D1")
WARM = ("#FFD27A", "#C9922A")
GRAY = ("#E5E7EB", "#9CA3AF")
RED = ("#FF8A80", "#C45C5C")

AGENT = {
    "waking": "listening",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "talking",
    "stuck": "thinking",
}


def agent_state(phase: str) -> str | None:
    return AGENT.get(phase)


def clamp01(n: float) -> float:
    if n != n or n == float("inf") or n == float("-inf"):
        return 0.0
    return 0.0 if n < 0.0 else 1.0 if n > 1.0 else n


def volumes(agent: str | None, t: float, *, mic_rms: float = 0.0, rms: float = 0.0) -> tuple[float, float]:
    if agent is None:
        vin, vout = 0.0, 0.3
    elif agent == "listening":
        vin, vout = clamp01(0.55 + math.sin(t * 3.2) * 0.35), 0.45
        vin = max(vin, min(1.0, mic_rms * 4.2))
    elif agent == "talking":
        vin = clamp01(0.65 + math.sin(t * 4.8) * 0.22)
        vout = clamp01(0.75 + math.sin(t * 3.6) * 0.22)
        vout = max(vout, min(1.0, rms * 4.2))
    else:
        base = 0.38 + 0.07 * math.sin(t * 0.7)
        wander = 0.05 * math.sin(t * 2.1) * math.sin(t * 0.37 + 1.2)
        vin = clamp01(base + wander)
        vout = clamp01(0.48 + 0.12 * math.sin(t * 1.05 + 0.6))
    return vin, vout


def palette(*, phase: str, card: bool, muted: bool) -> tuple[str, str]:
    if muted:
        return GRAY
    if phase == "stuck":
        return RED
    if card:
        return WARM
    return DEFAULT


def hex_rgb(color: str) -> tuple[float, float, float]:
    h = color.lstrip("#")
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def splitmix32(a: int):
    a &= 0xFFFFFFFF

    def rnd() -> float:
        nonlocal a
        a = (a + 0x9E3779B9) & 0xFFFFFFFF
        t = a ^ (a >> 16)
        t = (t * 0x21F0AAAD) & 0xFFFFFFFF
        t ^= t >> 15
        t = (t * 0x735A2D97) & 0xFFFFFFFF
        t = (t ^ (t >> 15)) & 0xFFFFFFFF
        return t / 4294967296

    return rnd


@lru_cache(maxsize=1)
def _offsets(seed: int = SEED) -> tuple[float, ...]:
    rnd = splitmix32(seed)
    return tuple(rnd() * PI * 2 for _ in range(7))


def render(
    size: int,
    *,
    agent: str | None,
    t: float,
    mic_rms: float = 0.0,
    rms: float = 0.0,
    colors: tuple[str, str] = DEFAULT,
    inverted: float = 0.0,
) -> Image.Image:
    size = max(32, int(size))
    vin, vout = volumes(agent, t, mic_rms=mic_rms, rms=rms)
    u_time = t * 0.5
    speed = 0.1 + (1.0 - (vout - 1.0) ** 2) * 0.9
    u_anim = t * speed
    c1, c2 = hex_rgb(colors[0]), hex_rgb(colors[1])
    try:
        import numpy as np

        return _numpy(
            size, u_time, u_anim, vin, vout, c1, c2, inverted, _offsets()
        )
    except ImportError:
        return _fallback(size, vin, vout, colors, agent, t)


def _numpy(size, u_time, u_anim, vin, vout, c1, c2, inverted, offsets) -> Image.Image:
    import numpy as np

    ys = np.linspace(1.0, -1.0, size, dtype=np.float32)
    xs = np.linspace(-1.0, 1.0, size, dtype=np.float32)
    x, y = np.meshgrid(xs, ys)
    radius = np.hypot(x, y)
    theta = np.arctan2(y, x)
    theta = np.where(theta < 0.0, theta + 2.0 * PI, theta)
    dec_x = theta / (2.0 * PI)
    dec_y = np.mod(theta / (2.0 * PI) + 0.5, 1.0) + 1.0
    dec_z = np.abs(theta / PI - 1.0)

    tex = _perlin()
    flow = (
        _sample(tex, u_anim * -0.2 + radius * 0.03, dec_x / 2.0) * (1.0 - dec_z)
        + _sample(tex, u_anim * -0.2 + radius * 0.03, dec_y / 2.0) * dec_z
    )
    theta = theta + (flow - 0.5) * (0.08 + 0.17 * vout)

    gray = np.ones((size, size), dtype=np.float32)
    centers0 = (0.0, 0.5 * PI, 1.0 * PI, 1.5 * PI, 2.0 * PI, 2.5 * PI, 3.0 * PI)
    for i, orig in enumerate(centers0):
        center = orig + 0.5 * math.sin(u_time / 20.0 + offsets[i])
        noise = float(_sample(tex, (center + u_time * 0.05) % 1.0, 0.5))
        a = 0.5 + noise * 0.3
        b = max(0.05, noise * (3.5 - vin))
        dist = np.minimum(
            np.abs(theta - center),
            np.minimum(np.abs(theta + 2.0 * PI - center), np.abs(theta - 2.0 * PI - center)),
        )
        oval = (dist * dist) / (a * a) + (radius * radius) / (b * b)
        edge = _smoothstep(1.0, 1.0 - 0.6, oval)
        gradient = (dist / a + 1.0) / 2.0
        if i % 2 == 1:
            gradient = 1.0 - gradient
        gradient = 0.5 * 0.9 + gradient * 0.1
        contrib = 0.85 * edge
        gray = gray * (1.0 - contrib) + gradient * contrib

    ring1 = _ring(dec_x, dec_y, dec_z, u_time * 0.1, 1.0, 0.3, 5.0, 2.5)
    ring2 = _ring(dec_x, dec_y, dec_z, u_time * 0.1, 0.9, 0.2, 6.0, 5.0)
    input_r1 = radius + vin * 0.2
    input_r2 = radius + vin * 0.15
    op1 = 0.2 + 0.4 * vin
    op2 = 0.15 + 0.3 * vin
    ra1 = np.where(input_r2 >= ring1, op1, 0.0)
    ra2 = _smoothstep(ring2 - 0.05, ring2 + 0.05, input_r1) * op2
    ring_a = np.maximum(ra1, ra2)
    gray = 1.0 - (1.0 - gray) * (1.0 - ring_a)

    lum = gray * (1.0 - inverted) + (1.0 - gray) * inverted
    rgb = _ramp(lum, c1, c2)
    alpha = np.clip((1.02 - radius) / 0.04, 0.0, 1.0)
    out = np.zeros((size, size, 4), dtype=np.uint8)
    out[..., 0] = np.clip(rgb[0] * 255.0, 0, 255).astype(np.uint8)
    out[..., 1] = np.clip(rgb[1] * 255.0, 0, 255).astype(np.uint8)
    out[..., 2] = np.clip(rgb[2] * 255.0, 0, 255).astype(np.uint8)
    out[..., 3] = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _ring(dx, dy, dz, time, start, width, scale, amp):
    n = _noise2d(dx * scale, time * scale) * (1.0 - dz) + _noise2d(dy * scale, time * scale) * dz
    n = (n - 0.5) * amp
    return start + n * width * (1.5 if amp < 3.0 else 1.0)


def _noise2d(x, y):
    import numpy as np

    i = np.floor(x)
    j = np.floor(y)
    fx = x - i
    fy = y - j
    ux = fx * fx * (3.0 - 2.0 * fx)
    uy = fy * fy * (3.0 - 2.0 * fy)

    def grad(ix, iy, fxx, fyy):
        hx = np.sin(ix * 127.1 + iy * 311.7) * 43758.5453
        hy = np.sin(ix * 269.5 + iy * 183.3) * 43758.5453
        hx = hx - np.floor(hx)
        hy = hy - np.floor(hy)
        return hx * fxx + hy * fyy

    n00 = grad(i, j, fx, fy)
    n10 = grad(i + 1.0, j, fx - 1.0, fy)
    n01 = grad(i, j + 1.0, fx, fy - 1.0)
    n11 = grad(i + 1.0, j + 1.0, fx - 1.0, fy - 1.0)
    n = (n00 * (1.0 - ux) + n10 * ux) * (1.0 - uy) + (n01 * (1.0 - ux) + n11 * ux) * uy
    return 0.5 + 0.5 * n


def _smoothstep(e0, e1, x):
    import numpy as np

    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _ramp(g, c1, c2):
    import numpy as np

    black = (0.0, 0.0, 0.0)
    white = (1.0, 1.0, 1.0)
    t1 = np.clip(g * 3.0, 0.0, 1.0)
    t2 = np.clip((g - 0.33) * 3.0, 0.0, 1.0)
    t3 = np.clip((g - 0.66) * 3.0, 0.0, 1.0)
    lo = [(black[i] * (1.0 - t1) + c1[i] * t1) for i in range(3)]
    mid = [(c1[i] * (1.0 - t2) + c2[i] * t2) for i in range(3)]
    hi = [(c2[i] * (1.0 - t3) + white[i] * t3) for i in range(3)]
    out = []
    for i in range(3):
        ch = np.where(g < 0.33, lo[i], np.where(g < 0.66, mid[i], hi[i]))
        out.append(ch)
    return out


@lru_cache(maxsize=1)
def _perlin():
    import numpy as np

    rng = np.random.RandomState(SEED)
    base = (rng.rand(32, 32) * 255).astype("uint8")
    img = Image.fromarray(base, "L").resize((256, 256), Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(2))
    return (np.asarray(img, dtype="float32") / 255.0)


def _sample(tex, u, v):
    import numpy as np

    h, w = tex.shape
    x = np.mod(u, 1.0) * w
    y = np.mod(v, 1.0) * h
    x0 = np.floor(x).astype(np.int32) % w
    y0 = np.floor(y).astype(np.int32) % h
    x1 = (x0 + 1) % w
    y1 = (y0 + 1) % h
    fx = x - np.floor(x)
    fy = y - np.floor(y)
    return (
        tex[y0, x0] * (1.0 - fx) * (1.0 - fy)
        + tex[y0, x1] * fx * (1.0 - fy)
        + tex[y1, x0] * (1.0 - fx) * fy
        + tex[y1, x1] * fx * fy
    )


def _fallback(size, vin, vout, colors, agent, t) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    c1 = tuple(int(x * 255) for x in hex_rgb(colors[0]))
    c2 = tuple(int(x * 255) for x in hex_rgb(colors[1]))
    pulse = 0.5 + 0.5 * vin
    if agent == "talking":
        pulse = 0.55 + 0.45 * vout
    elif agent is None:
        pulse = 0.28 + 0.08 * abs(math.sin(t * 1.4))
    pad = int(size * (0.10 - 0.05 * pulse))
    fill = tuple(int(c1[i] * (1 - pulse) + c2[i] * pulse) for i in range(3))
    draw.ellipse((pad, pad, size - 1 - pad, size - 1 - pad), fill=(*fill, 255))
    hi = int(size * 0.22)
    hx, hy = pad + int(size * 0.22), pad + int(size * 0.18)
    draw.ellipse((hx, hy, hx + hi, hy + int(hi * 0.7)), fill=(255, 255, 255, 90))
    if agent == "listening":
        ring = max(2, size // 28)
        draw.ellipse((pad - 1, pad - 1, size - pad, size - pad), outline=(*c2, 220), width=ring)
    return img
