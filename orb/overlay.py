"""Frameless always-on-top orb. Subscribes via Presence; never opens a mic."""

from __future__ import annotations

import queue
import re
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Callable

from orb.draw import render_frame
from orb.presence import Presence

KEY = "#010203"


def parse_tk_origin(geo: str) -> tuple[int, int]:
    """Tk `WxH±X±Y` — signs travel with the number (`+12-40` is y=-40)."""
    found = re.findall(r"[+-]\d+", geo)
    if len(found) >= 2:
        return int(found[-2]), int(found[-1])
    return 0, 0


def _work_area() -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    ok = ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
    if not ok:
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _origin(size: int) -> tuple[int, int]:
    wa = _work_area()
    if wa:
        left, _top, right, bottom = wa
        return (left + right - size) // 2, bottom - size - 10
    return 200, 200


class Overlay:
    def __init__(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        size: int | None = None,
        on_toggle: Callable[[], None] | None = None,
        on_mute: Callable[[], None] | None = None,
        on_sleep: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        if size is None:
            w, h = int(width or 0), int(height or 0)
            if w >= 200 and 0 < h <= 80:
                size = 140
            else:
                size = max(w, h, 140)
        self.size = max(80, int(size))
        self.width = self.size
        self.height = self.size
        self._on_toggle = on_toggle
        self._on_mute = on_mute
        self._on_sleep = on_sleep
        self._on_close = on_close
        self._q: queue.Queue = queue.Queue()
        self._loop = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._root = None
        self._visible = True
        self._snap = Presence().snapshot()
        self._t0 = time.perf_counter()
        self._press = None
        self._dragged = False
        self._backend = "tk"

    def start(self, loop) -> bool:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return False
        self._loop = loop
        self._stop.clear()
        self._backend = "tk"
        self._thread = threading.Thread(target=self._run, name="voice-orb", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        try:
            self._tk_loop()
        except Exception:
            log = Path.cwd() / "data" / "orb-crash.log"
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(traceback.format_exc(), encoding="utf-8")
            except OSError:
                pass

    def push(self, presence: Presence) -> None:
        self._q.put(presence.snapshot())

    def hide(self) -> None:
        self._q.put({"_cmd": "hide"})

    def show(self) -> None:
        self._q.put({"_cmd": "show"})

    def toggle_visible(self) -> None:
        self._q.put({"_cmd": "toggle"})

    def stop(self) -> None:
        self._stop.set()
        self._q.put({"_cmd": "quit"})

    def _fire(self, cb: Callable[[], None] | None) -> None:
        if cb is None:
            return
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(cb)
        else:
            cb()

    def _tk_loop(self) -> None:
        import tkinter as tk
        from PIL import ImageTk

        root = tk.Tk()
        self._root = root
        root.title("Friday")
        root.overrideredirect(True)
        root.wm_attributes("-topmost", True)
        try:
            root.wm_attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        root.configure(bg=KEY)
        w = h = self.size
        x, y = _origin(w)
        root.geometry(f"{w}x{h}+{x}+{y}")

        label = tk.Label(root, bg=KEY, bd=0, highlightthickness=0)
        label.pack(fill="both", expand=True)
        photo_holder = {"img": None}

        def on_down(e):
            try:
                wx, wy = int(root.winfo_x()), int(root.winfo_y())
            except tk.TclError:
                wx, wy = parse_tk_origin(root.geometry())
            self._press = (e.x_root, e.y_root, wx, wy)
            self._dragged = False

        def on_move(e):
            if self._press is None:
                return
            dx = e.x_root - self._press[0]
            dy = e.y_root - self._press[1]
            if abs(dx) + abs(dy) > 8:
                self._dragged = True
                root.geometry(f"+{self._press[2] + dx}+{self._press[3] + dy}")

        def on_up(_e):
            if self._press is not None and not self._dragged:
                self._fire(self._on_toggle)
            self._press = None

        def menu(_e):
            m = tk.Menu(root, tearoff=0)
            muted = bool(self._snap.get("muted"))
            m.add_command(label="Unmute mic" if muted else "Mute mic", command=lambda: self._fire(self._on_mute))
            m.add_command(label="Sleep", command=lambda: self._fire(self._on_sleep))
            m.add_separator()
            m.add_command(label="Close orb", command=lambda: self._fire(self._on_close))
            try:
                m.tk_popup(_e.x_root, _e.y_root)
            finally:
                m.grab_release()

        for widget in (root, label):
            widget.bind("<ButtonPress-1>", on_down)
            widget.bind("<B1-Motion>", on_move)
            widget.bind("<ButtonRelease-1>", on_up)
            widget.bind("<Button-3>", menu)

        def tick():
            if self._stop.is_set():
                root.destroy()
                return
            try:
                while True:
                    item = self._q.get_nowait()
                    cmd = item.get("_cmd") if isinstance(item, dict) else None
                    if cmd == "hide":
                        root.withdraw()
                        self._visible = False
                    elif cmd == "show":
                        root.deiconify()
                        root.wm_attributes("-topmost", True)
                        self._visible = True
                    elif cmd == "toggle":
                        (self.hide if self._visible else self.show)()
                    elif cmd == "quit":
                        self._stop.set()
                        root.destroy()
                        return
                    else:
                        self._snap = item
            except queue.Empty:
                pass

            now = time.perf_counter()
            frame = render_frame(
                phase=self._snap.get("phase") or "idle",
                rms=float(self._snap.get("rms") or 0),
                mic_rms=float(self._snap.get("mic_rms") or 0),
                card=bool(self._snap.get("card")),
                muted=bool(self._snap.get("muted")),
                size=self.size,
                t=now - self._t0,
            )
            photo = ImageTk.PhotoImage(frame)
            photo_holder["img"] = photo
            label.configure(image=photo)
            root.after(16, tick)

        root.after(16, tick)
        try:
            root.mainloop()
        finally:
            self._root = None
