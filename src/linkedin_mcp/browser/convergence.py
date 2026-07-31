"""Shared bounded settling for asynchronously rendered visible collections."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from playwright.async_api import Locator, Page

CollectionSignature = tuple[str, ...]
SignatureReader = Callable[[], Awaitable[CollectionSignature]]
EndReader = Callable[[], Awaitable[bool]]


class CollectionSettleOutcome(StrEnum):
    """What became observable during one bounded post-interaction wait."""

    PROGRESSED = "progressed"
    EXPLICIT_END = "explicit_end"
    IDLE = "idle"


@dataclass(frozen=True, slots=True)
class CollectionSettleResult:
    outcome: CollectionSettleOutcome
    signature: CollectionSignature


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
