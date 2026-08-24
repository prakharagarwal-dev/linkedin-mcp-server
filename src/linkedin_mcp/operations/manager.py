"""Serialize complete LinkedIn operations with one process-local lock."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress


class OperationManager:
    """Allow exactly one complete LinkedIn operation to execute at a time."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_operation: str | None = None
        self._waiting_operations = 0

    @property
    def active(self) -> bool:
        return self._lock.locked()

    @property
    def active_operation(self) -> str | None:
        return self._active_operation

    @property
    def waiting_operations(self) -> int:
        return self._waiting_operations

    async def run[ResultT](
        self,
        name: str,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        """Run one cancellable read operation while exclusively holding the lock."""

        return await self._run(name, operation, complete_after_cancellation=False)

    async def run_write[ResultT](
        self,
        name: str,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        """Finish an already-started write even if its requesting client disconnects."""

        return await self._run(name, operation, complete_after_cancellation=True)

    async def _run[ResultT](
        self,
        name: str,
        operation: Callable[[], Awaitable[ResultT]],
        *,
        complete_after_cancellation: bool,
    ) -> ResultT:
        self._waiting_operations += 1
        acquired = False
        try:
            await self._lock.acquire()
            acquired = True
            self._waiting_operations -= 1
            self._active_operation = name
            if complete_after_cancellation:
                return await self._run_to_completion(name, operation)
            return await operation()
        finally:
            if not acquired:
                self._waiting_operations -= 1
            else:
                self._active_operation = None
                self._lock.release()

    @staticmethod
    async def _run_to_completion[ResultT](
        name: str,
        operation: Callable[[], Awaitable[ResultT]],
    ) -> ResultT:
        async def invoke() -> ResultT:
            return await operation()

        running = asyncio.create_task(invoke(), name=f"linkedin-operation:{name}")
        cancellation: asyncio.CancelledError | None = None
        while not running.done():
            try:
                await asyncio.shield(running)
            except asyncio.CancelledError as error:
                cancellation = error
        if cancellation is not None:
            with suppress(BaseException):
                running.result()
            raise cancellation
        return running.result()
