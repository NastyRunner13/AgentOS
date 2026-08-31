"""Overlay presence. Subscribes to the bus; never captures audio."""

from orb.draw import render_frame
from orb.presence import Presence
from orb.shader import agent_state

__all__ = ["Presence", "Overlay", "render_frame", "agent_state"]


def __getattr__(name: str):
    if name == "Overlay":
        from orb.overlay import Overlay

        return Overlay
    raise AttributeError(name)
