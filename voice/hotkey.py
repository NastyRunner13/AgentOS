"""Global hotkey. Windows message pump in a daemon thread; no-op elsewhere."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable


def parse(hotkey: str) -> tuple[int, int] | None:
    raw = (hotkey or "").strip().lower()
    if not raw or raw in ("none", "off"):
        return None
    mods = 0
    vk = 0
    for part in raw.replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= 0x0002
        elif part == "shift":
            mods |= 0x0004
        elif part in ("alt", "menu"):
            mods |= 0x0001
        elif part in ("win", "super", "meta"):
            mods |= 0x0008
        elif part == "space":
            vk = 0x20
        elif len(part) == 1 and part.isalpha():
            vk = ord(part.upper())
        elif len(part) == 1 and part.isdigit():
            vk = ord(part)
        else:
            return None
    if vk == 0:
        return None
    return mods, vk


class Hotkey:
    def __init__(self, hotkey: str, callback: Callable[[], None]) -> None:
        self._spec = parse(hotkey)
        self._callback = callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._spec is None or sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="voice-hotkey", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        mods, vk = self._spec
        # MOD_NOREPEAT (0x4000): hold should not start/stop/start listen on key repeat.
        if not user32.RegisterHotKey(None, 1, mods | 0x4000, vk):
            if not user32.RegisterHotKey(None, 1, mods, vk):
                return
        try:
            msg = wintypes.MSG()
            while not self._stop.is_set():
                got = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)
                if got and msg.message == 0x0312:  # WM_HOTKEY
                    try:
                        self._callback()
                    except Exception:
                        pass
                else:
                    time.sleep(0.03)
        finally:
            user32.UnregisterHotKey(None, 1)
