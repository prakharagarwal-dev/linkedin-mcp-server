"""One queued unit of asynchronous work and its eventual result."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextvars import Context, copy_context
from dataclasses import dataclass, field


def _observe_result[ResultT](future: asyncio.Future[ResultT]) -> None:
    if not future.cancelled():
        future.exception()


@dataclass(slots=True)
class Task[ResultT]:
    """Carry one callable from its submitting tool to the worker."""

    name: str
    execute: Callable[[], Awaitable[ResultT]]
    interruptible: bool = True
    _context: Context = field(default_factory=copy_context, init=False, repr=False)
    _future: asyncio.Future[ResultT] = field(init=False, repr=False)
    _running: asyncio.Task[ResultT] | None = field(default=None, init=False, repr=False)
    _cancel_requested: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        future = asyncio.get_running_loop().create_future()
        future.add_done_callback(_observe_result)
        self._future = future

    @property
    def done(self) -> bool:
        return self._future.done()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    async def result(self) -> ResultT:
        """Wait for the worker result without transferring caller cancellation."""

        try:
            return await asyncio.shield(self._future)
        except asyncio.CancelledError:
            self.cancel()
            raise

    def cancel(self) -> None:
        """Skip queued work or interrupt a running read task."""

        self._cancel_requested = True
        running = self._running
        if running is not None and self.interruptible:
            running.cancel()
        if not self._future.done():
            self._future.cancel()

    def reject(self, error: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(error)

    async def run(self) -> None:
        """Execute once and settle the result future."""

        if self._cancel_requested or self._future.cancelled():
            return
        running: asyncio.Task[ResultT] = asyncio.create_task(
            self._invoke(),
            name=f"linkedin-task:{self.name}",
            context=self._context,
        )
        self._running = running
        try:
            result = await running
        except asyncio.CancelledError:
            if not self._future.done():
                self._future.cancel()
        except Exception as error:
            if not self._future.done():
                self._future.set_exception(error)
        else:
            if not self._future.done():
                self._future.set_result(result)
        finally:
            self._running = None

    async def _invoke(self) -> ResultT:
        return await self.execute()
