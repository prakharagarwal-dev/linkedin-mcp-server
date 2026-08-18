from __future__ import annotations

import asyncio
from contextvars import ContextVar

import pytest

from linkedin_mcp.errors import BrowserUnavailableError
from linkedin_mcp.execution import Scheduler, Task, Worker


@pytest.mark.asyncio
async def test_scheduler_runs_tasks_fifo_on_one_worker() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=3)
    order: list[str] = []
    first_release = asyncio.Event()

    async def first() -> str:
        order.append("first-start")
        await first_release.wait()
        order.append("first-end")
        return "first-result"

    async def second() -> str:
        order.append("second")
        return "second-result"

    await scheduler.start()
    first_task = Task(name="first", execute=first)
    second_task = Task(name="second", execute=second)
    await scheduler.schedule(first_task)
    await scheduler.schedule(second_task)
    await asyncio.sleep(0)

    assert scheduler.active is True
    assert scheduler.active_task == "first"
    assert scheduler.queue_depth == 1

    first_release.set()
    assert await first_task.result() == "first-result"
    assert await second_task.result() == "second-result"
    assert order == ["first-start", "first-end", "second"]
    await scheduler.close()


@pytest.mark.asyncio
async def test_scheduler_rejects_tasks_when_stopped_or_full() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=1)

    async def value() -> str:
        return "value"

    stopped = Task(name="stopped", execute=value)
    with pytest.raises(BrowserUnavailableError, match="not running"):
        await scheduler.schedule(stopped)

    release = asyncio.Event()

    async def blocked() -> None:
        await release.wait()

    await scheduler.start()
    active = Task(name="active", execute=blocked)
    queued = Task(name="queued", execute=blocked)
    overflow = Task(name="overflow", execute=blocked)
    await scheduler.schedule(active)
    await asyncio.sleep(0)
    await scheduler.schedule(queued)
    with pytest.raises(BrowserUnavailableError, match="queue is full"):
        await scheduler.schedule(overflow)

    release.set()
    await active.result()
    await queued.result()
    await scheduler.close()


@pytest.mark.asyncio
async def test_task_preserves_submission_context_and_propagates_failure() -> None:
    identity: ContextVar[str] = ContextVar("identity", default="none")
    worker = Worker()
    scheduler = Scheduler(worker, capacity=2)
    await scheduler.start()

    token = identity.set("client-a")

    async def read_identity() -> str:
        return identity.get()

    contextual = Task(name="context", execute=read_identity)
    identity.reset(token)
    await scheduler.schedule(contextual)
    assert await contextual.result() == "client-a"

    async def fail() -> None:
        raise ValueError("broken task")

    failed = Task(name="failure", execute=fail)
    await scheduler.schedule(failed)
    with pytest.raises(ValueError, match="broken task"):
        await failed.result()
    await scheduler.close()


@pytest.mark.asyncio
async def test_quiesce_rejects_queued_task_and_waits_for_active_task() -> None:
    worker = Worker()
    scheduler = Scheduler(worker, capacity=2)
    release = asyncio.Event()
    started = asyncio.Event()

    async def blocked() -> str:
        started.set()
        await release.wait()
        return "finished"

    await scheduler.start()
    active = Task(name="active", execute=blocked)
    queued = Task(name="queued", execute=blocked)
    await scheduler.schedule(active)
    await started.wait()
    await scheduler.schedule(queued)

    quiescing = asyncio.create_task(scheduler.quiesce())
    await asyncio.sleep(0)
    assert quiescing.done() is False
    with pytest.raises(BrowserUnavailableError, match="shutting down"):
        await queued.result()

    release.set()
    assert await active.result() == "finished"
    await quiescing
    assert scheduler.accepting is False
    await scheduler.close()
