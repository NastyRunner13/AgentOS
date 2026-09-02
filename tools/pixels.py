"""Set-of-Marks screenshots and click/type at coordinates. Last resort."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from tools.a11y import Node

MODEL_MAX_SIDE = 1280


class LivePixels:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.origin = (0, 0)
        self.size = (0, 0)
        self.image_size = (0, 0)
        self._dpi()

    def _dpi(self) -> None:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def meta(self) -> dict:
        model = self.data_dir / "screen-model.png"
        shot = model if model.is_file() else self.data_dir / "screen-last.png"
        return {
            "screenshot": str(shot) if shot.is_file() else "",
            "size": list(self.size),
            "image_size": list(self.image_size or self.size),
            "origin": list(self.origin),
        }

    def from_image(self, x: int, y: int) -> tuple[int, int]:
        """Map click coords onto the physical screen.

        0–1000 inclusive is Gemini's normalized space (the only space the
        attached screenshot is labeled in). Values above 1000 are treated
        as pixels in the attached image.
        """
        ow, oh = self.size
        iw, ih = self.image_size or self.size
        x, y = int(x), int(y)
        if 0 <= x <= 1000 and 0 <= y <= 1000:
            if ow and oh:
                x, y = round(x * ow / 1000), round(y * oh / 1000)
            elif iw and ih:
                x, y = round(x * iw / 1000), round(y * ih / 1000)
        elif iw and ih and ow and oh and (iw, ih) != (ow, oh):
            x = round(x * ow / iw)
            y = round(y * oh / ih)
        if ow and oh:
            x = min(max(0, x), ow - 1)
            y = min(max(0, y), oh - 1)
        return int(x), int(y)

    async def screenshot(self) -> bytes:
        import mss
        from PIL import Image

        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            self.origin = (int(mon["left"]), int(mon["top"]))
            raw = sct.grab(mon)
        im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        self.size = im.size
        buf = BytesIO()
        im.save(buf, format="PNG")
        data = buf.getvalue()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "screen-last.png").write_bytes(data)
        (self.data_dir / "screen-model.png").write_bytes(self._downscale(data))
        return data

    def _downscale(self, png: bytes) -> bytes:
        from PIL import Image

        im = Image.open(BytesIO(png)).convert("RGB")
        if max(im.size) > MODEL_MAX_SIDE:
            im.thumbnail((MODEL_MAX_SIDE, MODEL_MAX_SIDE))
        self.image_size = im.size
        self._draw_axes(im)
        buf = BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    def _draw_axes(self, im) -> None:
        from PIL import ImageDraw

        draw = ImageDraw.Draw(im)
        w, h = im.size
        draw.rectangle([0, 0, w, 16], fill=(0, 0, 0))
        draw.text((4, 2), "x,y: 0-1000  (0,0) top-left  (1000,1000) bottom-right", fill=(0, 255, 80))
        for t in (0, 250, 500, 750, 1000):
            x = round(t * (w - 1) / 1000)
            y = round(t * (h - 1) / 1000)
            draw.line([(x, 16), (x, 24)], fill=(0, 255, 80))
            draw.line([(0, y), (8, y)], fill=(0, 255, 80))

    def mark_click(self, sx: int, sy: int) -> None:
        from PIL import Image, ImageDraw

        path = self.data_dir / "screen-model.png"
        if not path.is_file():
            return
        im = Image.open(path).convert("RGB")
        iw, ih = im.size
        ow, oh = self.size or im.size
        ix = round(int(sx) * (iw - 1) / ow) if ow else int(sx)
        iy = round(int(sy) * (ih - 1) / oh) if oh else int(sy)
        draw = ImageDraw.Draw(im)
        draw.ellipse([ix - 12, iy - 12, ix + 12, iy + 12], outline=(255, 0, 0), width=2)
        draw.line([(ix - 18, iy), (ix + 18, iy)], fill=(255, 0, 0), width=2)
        draw.line([(ix, iy - 18), (ix, iy + 18)], fill=(255, 0, 0), width=2)
        im.save(path)

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
        import asyncio
        import ctypes

        ox, oy = self.origin
        ow, oh = self.size
        x, y = int(x), int(y)
        if ow and oh:
            x = min(max(0, x), ow - 1)
            y = min(max(0, y), oh - 1)
        ctypes.windll.user32.SetCursorPos(x + ox, y + oy)
        await asyncio.sleep(0.05)
        ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)
        await asyncio.sleep(0.05)
        ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)

    async def scroll_xy(self, x: int, y: int, dy: int) -> None:
        import ctypes

        ox, oy = self.origin
        ctypes.windll.user32.SetCursorPos(int(x) + ox, int(y) + oy)
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(dy), 0)

    async def type_text(self, text: str) -> None:
        from pywinauto.keyboard import send_keys

        send_keys(text, with_spaces=True)
