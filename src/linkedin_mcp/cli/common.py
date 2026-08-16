"""Shared lifecycle helpers for CLI commands."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from types import FrameType

from linkedin_mcp.config import Settings
from linkedin_mcp.runtime import AccountProcessLock


def settings_for_transport(transport: str | None = None) -> Settings:
    settings = Settings()
    if transport is None:
        return settings
    values = settings.model_dump()
    values["transport"] = transport
    return Settings.model_validate(values)


@contextmanager
def claim_account_runtime(
    settings: Settings,
    *,
    command: str,
) -> Generator[AccountProcessLock, None, None]:
    lock = AccountProcessLock(
        settings.runtime_lock_path,
        account_id=settings.account_id,
        command=command,
    )
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


async def run_owned_operation[ResultT](
    settings: Settings,
    *,
    command: str,
    operation: Callable[[], Awaitable[ResultT]],
) -> ResultT:
    with claim_account_runtime(settings, command=command) as process_lock:
        operation_task = asyncio.ensure_future(operation())
        stop_task = asyncio.create_task(wait_for_owned_operation_stop(process_lock))
        try:
            done, _ = await asyncio.wait(
                (operation_task, stop_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return await operation_task

            reason = await stop_task
            if operation_task.done():
                return await operation_task
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise RuntimeError(f"The {command} operation was interrupted by {reason}.")
        finally:
            if not operation_task.done():
                operation_task.cancel()
            if not stop_task.done():
                stop_task.cancel()
            await asyncio.gather(operation_task, stop_task, return_exceptions=True)


async def wait_for_stop_signal() -> signal.Signals:
    """Wait for a console stop signal using APIs available on every supported OS."""

    loop = asyncio.get_running_loop()
    received: asyncio.Future[signal.Signals] = loop.create_future()

    def receive(signum: int, _: FrameType | None) -> None:
        if not received.done():
            received.set_result(signal.Signals(signum))

    watched = (signal.SIGINT, signal.SIGTERM)
    previous = {watched_signal: signal.getsignal(watched_signal) for watched_signal in watched}
    try:
        for watched_signal in watched:
            signal.signal(watched_signal, receive)
        return await received
    finally:
        for watched_signal, handler in previous.items():
            signal.signal(watched_signal, handler)


async def wait_for_owned_operation_stop(process_lock: AccountProcessLock) -> str:
    request_task = asyncio.create_task(process_lock.wait_for_stop_request())
    signal_task = asyncio.create_task(wait_for_stop_signal())
    try:
        done, _ = await asyncio.wait(
            (request_task, signal_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if signal_task in done:
            return (await signal_task).name
        await request_task
        return "a graceful stop request"
    finally:
        for task in (request_task, signal_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(request_task, signal_task, return_exceptions=True)
