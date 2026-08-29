"""Event bus. Topics are strings; payloads are dicts."""

from __future__ import annotations

import asyncio
import uuid


def new_id() -> str:
    return uuid.uuid4().hex[:8]


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(topic, []).append(q)
        return q

    def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(topic)
        if not subs:
            return
        try:
            subs.remove(q)
        except ValueError:
            pass

    def publish(self, topic: str, payload: dict) -> None:
        item = dict(payload)
        item.setdefault("topic", topic)
        for q in list(self._subs.get(topic, [])):
            q.put_nowait(item)
