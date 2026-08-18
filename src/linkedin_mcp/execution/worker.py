"""Execute one queued task at a time."""

from __future__ import annotations

import asyncio

from linkedin_mcp.execution.task import Task


class Worker:
    """Run the task selected by the scheduler."""

    def __init__(self) -> None:
        self._active: Task[object] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def active(self) -> bool:
        return self._active is not None

    @property
    def active_task(self) -> str | None:
        task = self._active
        return task.name if task is not None else None

    async def execute(self, task: Task[object]) -> None:
        self._active = task
        self._idle.clear()
        try:
            await task.run()
        finally:
            self._active = None
            self._idle.set()

    def cancel_active(self) -> None:
        task = self._active
        if task is not None:
            task.cancel()

    async def wait_until_idle(self) -> None:
        await self._idle.wait()
