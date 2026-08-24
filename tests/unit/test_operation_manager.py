from __future__ import annotations

import asyncio

import pytest

from linkedin_mcp.operations import OperationManager


@pytest.mark.asyncio
async def test_operation_manager_serializes_complete_operations() -> None:
    manager = OperationManager()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    events: list[str] = []

    async def first() -> str:
        events.append("first-start")
        first_started.set()
        await release_first.wait()
        events.append("first-end")
        return "first"

    async def second() -> str:
        events.append("second-start")
        return "second"

    first_task = asyncio.create_task(manager.run("first", first))
    await first_started.wait()
    second_task = asyncio.create_task(manager.run("second", second))
    await asyncio.sleep(0)

    assert manager.active is True
    assert manager.active_operation == "first"
    assert manager.waiting_operations == 1
    assert events == ["first-start"]

    release_first.set()
    assert await first_task == "first"
    assert await second_task == "second"
    assert events == ["first-start", "first-end", "second-start"]
    assert manager.active is False


@pytest.mark.asyncio
async def test_cancelling_a_read_releases_the_operation_lock() -> None:
    manager = OperationManager()
    started = asyncio.Event()

    async def read() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(manager.run("read", read))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert await manager.run("next", _value) == "done"


@pytest.mark.asyncio
async def test_started_write_finishes_before_cancellation_releases_the_lock() -> None:
    manager = OperationManager()
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def write() -> None:
        started.set()
        await release.wait()
        finished.set()

    task = asyncio.create_task(manager.run_write("write", write))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)

    assert task.done() is False
    assert manager.active_operation == "write"

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert manager.active is False


@pytest.mark.asyncio
async def test_cancelled_waiter_never_invokes_its_operation() -> None:
    manager = OperationManager()
    release = asyncio.Event()
    invoked = False

    async def first() -> None:
        await release.wait()

    async def waiting() -> None:
        nonlocal invoked
        invoked = True

    first_task = asyncio.create_task(manager.run("first", first))
    await asyncio.sleep(0)
    waiting_task = asyncio.create_task(manager.run("waiting", waiting))
    await asyncio.sleep(0)
    waiting_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting_task
    release.set()
    await first_task

    assert invoked is False
    assert manager.waiting_operations == 0


async def _value() -> str:
    return "done"
