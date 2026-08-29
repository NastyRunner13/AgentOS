"""Concurrent tasks with steer routing."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from kernel.bus import Bus, new_id


class Task:
    def __init__(self, id: str, title: str) -> None:
        self.id = id
        self.title = title
        self.status = "queued"
        self.progress = 0.0
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.error: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
        }


Factory = Callable[[Task], Coroutine[Any, Any, Any]]


class TaskManager:
    def __init__(self, bus: Bus, concurrent_slots: int = 4) -> None:
        self.bus = bus
        self.slots = concurrent_slots
        self.tasks: dict[str, Task] = {}
        self._queue: list[tuple[Task, Factory]] = []
        self._running = 0

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def spawn(self, title: str, factory: Factory) -> Task:
        task = Task(new_id(), title)
        self.tasks[task.id] = task
        self._queue.append((task, factory))
        self.bus.publish("task.update", task.as_dict())
        self._pump()
        return task

    async def steer(self, task_id: str, message: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task {task_id}")
        if task.status in ("done", "failed"):
            raise ValueError(f"task {task_id} is {task.status}")
        await task.inbox.put(message)
        self.bus.publish(
            "task.update",
            {**task.as_dict(), "steered": message},
        )
        return task

    def _pump(self) -> None:
        while self._running < self.slots and self._queue:
            task, factory = self._queue.pop(0)
            self._running += 1
            asyncio.create_task(self._run(task, factory), name=f"task-{task.id}")

    async def _run(self, task: Task, factory: Factory) -> None:
        task.status = "running"
        self.bus.publish("task.update", task.as_dict())
        try:
            await factory(task)
            if task.status == "running":
                task.status = "done"
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            self.bus.publish("error", {"task_id": task.id, "error": str(exc)})
        finally:
            self._running -= 1
            self.bus.publish("task.update", task.as_dict())
            self._pump()
