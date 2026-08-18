from __future__ import annotations

import asyncio

import pytest

from linkedin_mcp.queue import Scheduler, Task, Worker


@pytest.mark.asyncio
async def test_cancelled_queued_task_is_never_executed() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=2)
    release = asyncio.Event()
    executed = False

    async def blocked() -> None:
        await release.wait()

    async def queued_operation() -> None:
        nonlocal executed
        executed = True

    await scheduler.start()
    active = Task(name="active", execute=blocked)
    queued = Task(name="queued", execute=queued_operation)
    await scheduler.schedule(active)
    await asyncio.sleep(0)
    await scheduler.schedule(queued)
    queued.cancel()
    release.set()
    await active.result()
    await worker.wait_until_idle()

    assert queued.done is True
    assert executed is False
    await scheduler.close()


@pytest.mark.asyncio
async def test_cancelled_active_read_is_interrupted() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=1)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def read() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    await scheduler.start()
    task = Task(name="read", execute=read)
    await scheduler.schedule(task)
    waiter = asyncio.create_task(task.result())
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await cancelled.wait()
    await worker.wait_until_idle()
    await scheduler.close()


@pytest.mark.asyncio
async def test_cancelled_write_waiter_does_not_interrupt_started_action() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=1)
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def write() -> None:
        started.set()
        await release.wait()
        completed.set()

    await scheduler.start()
    task = Task(name="write", execute=write, interruptible=False)
    await scheduler.schedule(task)
    waiter = asyncio.create_task(task.result())
    await started.wait()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    assert completed.is_set() is False
    assert worker.active is True
    release.set()
    await worker.wait_until_idle()
    assert completed.is_set() is True
    await scheduler.close()


@pytest.mark.asyncio
async def test_close_interrupts_active_read_and_stops_scheduler() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=1)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def read() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    await scheduler.start()
    task = Task(name="read", execute=read)
    await scheduler.schedule(task)
    await started.wait()
    await scheduler.close()

    assert cancelled.is_set() is True
    assert scheduler.running is False
    assert worker.active is False
