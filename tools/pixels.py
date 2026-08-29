"""Set-of-Marks screenshots and click/type at coordinates. Last resort."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from tools.a11y import Node


class LivePixels:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    async def screenshot(self) -> bytes:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(mon)
        im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    async def annotate(self, png: bytes, leftover: list[Node]) -> bytes:
        from PIL import Image, ImageDraw

        im = Image.open(BytesIO(png)).convert("RGB")
        draw = ImageDraw.Draw(im)
        if not leftover:
            draw.text((8, 8), "no a11y", fill=(255, 0, 0))
        for n in leftover:
            if not n.bounds:
                continue
            x, y, w, h = n.bounds
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=2)
            draw.text((x + 1, max(0, y - 12)), n.ref, fill=(255, 0, 0))
        buf = BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "som-last.png").write_bytes(data)
        return data

    async def click_xy(self, x: int, y: int) -> None:
        import ctypes

        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)

    async def type_text(self, text: str) -> None:
        from pywinauto.keyboard import send_keys

        send_keys(text, with_spaces=True)
