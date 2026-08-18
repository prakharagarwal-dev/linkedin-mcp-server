from __future__ import annotations

from typing import cast

import pytest
from playwright.async_api import Page

from linkedin_mcp.tools._shared.collections import (
    CollectionSettleOutcome,
    wait_for_collection_change,
    wait_for_collection_initial_state,
    wait_for_collection_interaction,
)


class _PollingPage:
    def __init__(self, updates: list[tuple[str, ...]]) -> None:
        self.updates = updates
        self.polls = 0

    async def wait_for_timeout(self, _: float) -> None:
        self.polls += 1

    async def signature(self) -> tuple[str, ...]:
        index = min(self.polls, len(self.updates) - 1)
        return self.updates[index]


@pytest.mark.asyncio
async def test_collection_settling_distinguishes_progress_from_timed_idleness() -> None:
    progressed_page = _PollingPage([("first",), ("first",), ("first", "second")])
    progressed = await wait_for_collection_change(
        cast(Page, progressed_page),
        baseline=("first",),
        read_signature=progressed_page.signature,
        attempts=4,
        delay_ms=1,
    )
    assert progressed.outcome is CollectionSettleOutcome.PROGRESSED
    assert progressed.signature == ("first", "second")

    idle_page = _PollingPage([("first",)])
    idle = await wait_for_collection_change(
        cast(Page, idle_page),
        baseline=("first",),
        read_signature=idle_page.signature,
        attempts=3,
        delay_ms=1,
    )
    assert idle.outcome is CollectionSettleOutcome.IDLE
    assert idle.signature == ("first",)
    assert idle_page.polls == 3


@pytest.mark.asyncio
async def test_collection_settling_accepts_only_an_explicit_end_signal() -> None:
    page = _PollingPage([("first",)])

    async def explicit_end() -> bool:
        return page.polls >= 2

    result = await wait_for_collection_change(
        cast(Page, page),
        baseline=("first",),
        read_signature=page.signature,
        read_explicit_end=explicit_end,
        attempts=4,
        delay_ms=1,
    )

    assert result.outcome is CollectionSettleOutcome.EXPLICIT_END
    assert page.polls == 2


@pytest.mark.asyncio
async def test_collection_progress_wins_when_tail_and_end_arrive_together() -> None:
    page = _PollingPage([("first",), ("first", "tail")])

    async def explicit_end() -> bool:
        return page.polls >= 1

    result = await wait_for_collection_change(
        cast(Page, page),
        baseline=("first",),
        read_signature=page.signature,
        read_explicit_end=explicit_end,
        attempts=2,
        delay_ms=1,
    )

    assert result.outcome is CollectionSettleOutcome.PROGRESSED
    assert result.signature == ("first", "tail")


@pytest.mark.asyncio
async def test_collection_interaction_retries_idle_delivery_within_one_poll_budget() -> None:
    page = _PollingPage([("first",)])
    interactions = 0

    async def interact() -> None:
        nonlocal interactions
        interactions += 1

    async def signature() -> tuple[str, ...]:
        if interactions >= 2:
            return ("first", "tail")
        return ("first",)

    result = await wait_for_collection_interaction(
        cast(Page, page),
        baseline=("first",),
        interact=interact,
        read_signature=signature,
        interaction_attempts=2,
        attempts=8,
        delay_ms=1,
    )

    assert result.outcome is CollectionSettleOutcome.PROGRESSED
    assert result.signature == ("first", "tail")
    assert interactions == 2
    assert page.polls == 5


@pytest.mark.asyncio
async def test_collection_interaction_does_not_retry_after_explicit_end() -> None:
    page = _PollingPage([("first",)])
    interactions = 0

    async def interact() -> None:
        nonlocal interactions
        interactions += 1

    async def explicit_end() -> bool:
        return page.polls >= 2

    result = await wait_for_collection_interaction(
        cast(Page, page),
        baseline=("first",),
        interact=interact,
        read_signature=page.signature,
        read_explicit_end=explicit_end,
        interaction_attempts=2,
        attempts=8,
        delay_ms=1,
    )

    assert result.outcome is CollectionSettleOutcome.EXPLICIT_END
    assert interactions == 1
    assert page.polls == 2


@pytest.mark.asyncio
async def test_initial_collection_state_observes_ready_and_explicit_empty_without_polling() -> None:
    ready_page = _PollingPage([("first",)])
    ready = await wait_for_collection_initial_state(
        cast(Page, ready_page),
        read_signature=ready_page.signature,
        attempts=2,
        delay_ms=1,
    )
    assert ready.outcome is CollectionSettleOutcome.PROGRESSED
    assert ready_page.polls == 0

    empty_page = _PollingPage([()])
    empty = await wait_for_collection_initial_state(
        cast(Page, empty_page),
        read_signature=empty_page.signature,
        read_explicit_end=lambda: _true(),
        attempts=2,
        delay_ms=1,
    )
    assert empty.outcome is CollectionSettleOutcome.EXPLICIT_END
    assert empty_page.polls == 0


async def _true() -> bool:
    return True


@pytest.mark.asyncio
async def test_collection_settling_rejects_unbounded_configuration() -> None:
    page = _PollingPage([()])
    with pytest.raises(ValueError, match="at least one"):
        await wait_for_collection_change(
            cast(Page, page),
            baseline=(),
            read_signature=page.signature,
            attempts=0,
        )
    with pytest.raises(ValueError, match="positive poll"):
        await wait_for_collection_change(
            cast(Page, page),
            baseline=(),
            read_signature=page.signature,
            delay_ms=0,
        )
    with pytest.raises(ValueError, match="at least one interaction"):
        await wait_for_collection_interaction(
            cast(Page, page),
            baseline=(),
            interact=_noop,
            read_signature=page.signature,
            interaction_attempts=0,
        )


async def _noop() -> None:
    return None
