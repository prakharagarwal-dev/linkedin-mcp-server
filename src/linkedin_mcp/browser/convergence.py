"""Shared bounded settling for asynchronously rendered visible collections."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

from playwright.async_api import Locator, Page

CollectionSignature = tuple[str, ...]
SignatureReader = Callable[[], Awaitable[CollectionSignature]]
EndReader = Callable[[], Awaitable[bool]]


class _EventDispatcher(Protocol):
    def dispatch_event(
        self,
        event_type: str,
        event_init: dict[str, object],
    ) -> Awaitable[None]: ...


class CollectionSettleOutcome(StrEnum):
    """What became observable during one bounded post-interaction wait."""

    PROGRESSED = "progressed"
    EXPLICIT_END = "explicit_end"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class CollectionSettleResult:
    outcome: CollectionSettleOutcome
    signature: CollectionSignature


async def dispatch_bubbling_wheel(locator: Locator, *, delta_y: int) -> None:
    """Dispatch one bounded locator-scoped wheel fallback with explicit typing."""

    dispatcher = cast(_EventDispatcher, locator)
    await dispatcher.dispatch_event(
        "wheel",
        {"bubbles": True, "cancelable": True, "deltaY": delta_y},
    )


async def wait_for_collection_change(
    page: Page,
    *,
    baseline: CollectionSignature,
    read_signature: SignatureReader,
    read_explicit_end: EndReader | None = None,
    attempts: int = 8,
    delay_ms: int = 250,
) -> CollectionSettleResult:
    """Wait for raw DOM progress without interpreting timed idleness as completion."""

    if attempts < 1:
        raise ValueError("Collection settling requires at least one poll attempt.")
    if delay_ms < 1:
        raise ValueError("Collection settling requires a positive poll delay.")

    signature = baseline
    for _ in range(attempts):
        await page.wait_for_timeout(delay_ms)
        signature = await read_signature()
        if signature != baseline:
            return CollectionSettleResult(
                outcome=CollectionSettleOutcome.PROGRESSED,
                signature=signature,
            )
        if read_explicit_end is not None and await read_explicit_end():
            return CollectionSettleResult(
                outcome=CollectionSettleOutcome.EXPLICIT_END,
                signature=signature,
            )
    return CollectionSettleResult(
        outcome=CollectionSettleOutcome.IDLE,
        signature=signature,
    )


async def wait_for_collection_interaction(
    page: Page,
    *,
    baseline: CollectionSignature,
    interact: Callable[[], Awaitable[None]],
    read_signature: SignatureReader,
    read_explicit_end: EndReader | None = None,
    interaction_attempts: int = 2,
    attempts: int = 8,
    delay_ms: int = 250,
) -> CollectionSettleResult:
    """Retry an idle UI interaction without expanding its total polling budget."""

    if interaction_attempts < 1:
        raise ValueError("Collection interaction settling requires at least one interaction.")
    if attempts < 1:
        raise ValueError("Collection interaction settling requires at least one poll attempt.")
    if delay_ms < 1:
        raise ValueError("Collection interaction settling requires a positive poll delay.")

    bounded_interactions = min(interaction_attempts, attempts)
    remaining_polls = attempts
    result = CollectionSettleResult(
        outcome=CollectionSettleOutcome.IDLE,
        signature=baseline,
    )
    for interaction_index in range(bounded_interactions):
        remaining_interactions = bounded_interactions - interaction_index
        poll_attempts = remaining_polls // remaining_interactions
        remaining_polls -= poll_attempts
        await interact()
        result = await wait_for_collection_change(
            page,
            baseline=baseline,
            read_signature=read_signature,
            read_explicit_end=read_explicit_end,
            attempts=poll_attempts,
            delay_ms=delay_ms,
        )
        if result.outcome is not CollectionSettleOutcome.IDLE:
            return result
    return result


async def wait_for_collection_initial_state(
    page: Page,
    *,
    read_signature: SignatureReader,
    read_explicit_end: EndReader | None = None,
    attempts: int = 8,
    delay_ms: int = 250,
) -> CollectionSettleResult:
    """Observe initial results or a visible terminal state within a bounded wait."""

    signature = await read_signature()
    if signature:
        return CollectionSettleResult(
            outcome=CollectionSettleOutcome.PROGRESSED,
            signature=signature,
        )
    if read_explicit_end is not None and await read_explicit_end():
        return CollectionSettleResult(
            outcome=CollectionSettleOutcome.EXPLICIT_END,
            signature=signature,
        )
    return await wait_for_collection_change(
        page,
        baseline=signature,
        read_signature=read_signature,
        read_explicit_end=read_explicit_end,
        attempts=attempts,
        delay_ms=delay_ms,
    )


async def visible_locator_signature(
    locator: Locator,
    *,
    identity_attributes: tuple[str, ...],
    limit: int = 500,
) -> CollectionSignature:
    """Return raw visible-node identities without depending on domain parsing."""

    if limit < 1:
        raise ValueError("Visible signature limit must be positive.")
    raw = await locator.evaluate_all(
        """
        (elements, options) => elements
          .filter(element => element.getClientRects().length > 0)
          .slice(0, options.limit)
          .map(element => {
            const attributes = options.identityAttributes
              .map(name => element.getAttribute(name) ?? "")
              .filter(Boolean);
            const text = element.innerText?.trim() ?? "";
            return [...attributes, text].filter(Boolean).join("\\u001f");
          })
          .filter(Boolean)
        """,
        {
            "identityAttributes": list(identity_attributes),
            "limit": limit,
        },
    )
    return tuple(value for value in cast(list[object], raw) if isinstance(value, str) and value)
