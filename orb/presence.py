"""Bus → visual state. No Tk, no mic."""

from __future__ import annotations

from orb.shader import agent_state

PHASES = frozenset(
    {"hidden", "idle", "waking", "listening", "thinking", "speaking", "stuck"}
)


class Presence:
    def __init__(self) -> None:
        self.phase = "idle"
        self.rms = 0.0
        self.mic_rms = 0.0
        self.card = False
        self.muted = False
        self.pending = 0

    def snapshot(self) -> dict:
        return {
            "phase": self.phase,
            "agent_state": agent_state(self.phase),
            "rms": self.rms,
            "mic_rms": self.mic_rms,
            "card": self.card,
            "muted": self.muted,
        }

    def on_state(self, ev: dict) -> None:
        phase = ev.get("phase")
        if phase == "token":
            if self.phase not in ("speaking", "listening", "waking"):
                self.phase = "thinking"
            return
        if phase not in PHASES:
            return
        self.phase = phase
        if phase in ("idle", "thinking", "stuck"):
            self.rms = 0.0
        if phase != "listening":
            self.mic_rms = 0.0

    def on_tts(self, ev: dict) -> None:
        self.rms = float(ev.get("rms") or 0)
        if self.rms > 0:
            self.phase = "speaking"

    def on_mic(self, ev: dict) -> None:
        self.mic_rms = float(ev.get("rms") or 0)
        if self.mic_rms > 0 and self.phase not in ("speaking", "thinking"):
            self.phase = "listening"

    def on_card(self, ev: dict) -> None:
        self.card = True
        self.pending += 1

    def on_resolved(self, ev: dict) -> None:
        self.pending = max(0, self.pending - 1)
        if self.pending == 0:
            self.card = False
