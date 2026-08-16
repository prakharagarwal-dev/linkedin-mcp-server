from __future__ import annotations

import asyncio

import pytest

from linkedin_mcp.app.scheduler import FairClientScheduler, SchedulerClosedError


@pytest.mark.asyncio
async def test_scheduler_preserves_client_fifo_and_round_robins_clients() -> None:
    scheduler = FairClientScheduler[str, str](capacity=10)
    await scheduler.put("client-a", "a-1")
    await scheduler.put("client-a", "a-2")
    await scheduler.put("client-b", "b-1")
    await scheduler.put("client-b", "b-2")

    assert [await scheduler.get() for _ in range(4)] == ["a-1", "b-1", "a-2", "b-2"]


@pytest.mark.asyncio
async def test_scheduler_gives_new_client_turn_after_current_client() -> None:
    scheduler = FairClientScheduler[str, str](capacity=10)
    await scheduler.put("client-a", "a-1")
    await scheduler.put("client-a", "a-2")
    assert await scheduler.get() == "a-1"

    await scheduler.put("client-b", "b-1")

    assert await scheduler.get() == "b-1"
    assert await scheduler.get() == "a-2"


@pytest.mark.asyncio
async def test_scheduler_capacity_close_and_identity_removal_are_bounded() -> None:
    scheduler = FairClientScheduler[str, object](capacity=1)
    first = object()
    second = object()
    await scheduler.put("client-a", first)
    waiting = asyncio.create_task(scheduler.put("client-b", second))
    await asyncio.sleep(0)
    assert waiting.done() is False

    assert await scheduler.remove("client-a", first) is True
    await waiting
    assert scheduler.qsize == 1
    assert await scheduler.close() == (second,)

    with pytest.raises(SchedulerClosedError):
        await scheduler.put("client-c", object())
    with pytest.raises(SchedulerClosedError):
        await scheduler.get()
