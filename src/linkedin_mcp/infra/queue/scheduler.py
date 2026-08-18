"""Bounded FIFO scheduling for the single local worker."""

from __future__ import annotations

import asyncio
from typing import Final, cast

from linkedin_mcp.errors import BrowserUnavailableError
from linkedin_mcp.infra.queue.task import Task
from linkedin_mcp.infra.queue.worker import Worker

_CLOSED: Final = object()


class Scheduler:
    """Take tasks from one asyncio queue and hand them to one worker."""

    def __init__(self, worker: Worker, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Scheduler capacity must be positive.")
        self._worker = worker
        self._queue: asyncio.Queue[Task[object] | object] = asyncio.Queue(capacity)
        self._task: asyncio.Task[None] | None = None
        self._accepting = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def active(self) -> bool:
        return self._worker.active

    @property
    def active_task(self) -> str | None:
        return self._worker.active_task

    async def start(self) -> None:
        if self.running:
            return
        self._accepting = True
        self._task = asyncio.create_task(self._run(), name="linkedin-scheduler")

    async def schedule[ResultT](self, task: Task[ResultT]) -> None:
        if not self._accepting or not self.running:
            error = BrowserUnavailableError("The local LinkedIn scheduler is not running.")
            task.reject(error)
            raise error
        try:
            self._queue.put_nowait(cast(Task[object], task))
        except asyncio.QueueFull as cause:
            error = BrowserUnavailableError("The local LinkedIn task queue is full.")
            task.reject(error)
            raise error from cause

    async def quiesce(self) -> None:
        """Reject queued work and let the active task reach a terminal result."""

        self._accepting = False
        self._reject_queued()
        await self._worker.wait_until_idle()

    async def close(self) -> None:
        self._accepting = False
        self._reject_queued()
        self._worker.cancel_active()
        await self._worker.wait_until_idle()

        loop = self._task
        self._task = None
        if loop is None:
            return
        self._queue.put_nowait(_CLOSED)
        await loop

    async def _run(self) -> None:
        while True:
            queued = await self._queue.get()
            try:
                if queued is _CLOSED:
                    return
                await self._worker.execute(cast(Task[object], queued))
            finally:
                self._queue.task_done()

    def _reject_queued(self) -> None:
        error = BrowserUnavailableError("The local LinkedIn scheduler is shutting down.")
        while True:
            try:
                queued = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                if queued is not _CLOSED:
                    cast(Task[object], queued).reject(error)
            finally:
                self._queue.task_done()
