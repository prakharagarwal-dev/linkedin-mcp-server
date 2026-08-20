"""Visible LinkedIn page implementation for `linkedin_mcp.tools.messaging.conversation.get.page`."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import cast

from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.browser.urls import (
    canonical_profile_url,
    conversation_id_from_url,
)
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.infra.playwright import Paced
from linkedin_mcp.infra.playwright.collections import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
from linkedin_mcp.tools.messaging.conversation.get.models import (
    ConversationCoverage,
    ConversationGetInput,
    ConversationObservation,
    MessageObservation,
    StopReason,
)
from linkedin_mcp.tools.messaging.conversation_surface import (
    ConversationSurface,
)
from linkedin_mcp.tools.messaging.conversation_surface import (
    MessageObservation as SurfaceMessageObservation,
)

_SCROLL_PROGRESS_POLL_ATTEMPTS = 8

_SCROLL_PROGRESS_POLL_DELAY_MS = 250

_HISTORY_END_CONFIRMATION_ROUNDS = 5


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _visible_text(locator: Locator) -> str:
    if await locator.count() == 0:
        raise ParserDriftError("LinkedIn messaging returned no visible container.")
    value = (await locator.first.inner_text()).strip()
    if not value:
        raise ParserDriftError("LinkedIn messaging returned no visible text.")
    return value


async def _raw_messages(root: Locator) -> list[dict[str, object]]:
    raw = await root.locator("li").evaluate_all(
        """
        elements => elements
          .filter(element => element.getClientRects().length > 0)
          .filter(element => (
            element.matches('[class*="msg-s-event-listitem"]') ||
            element.querySelector(
              '[class*="msg-s-event-listitem"],' +
              '[class*="event-listitem__body"],[data-test-message-body],' +
              '[data-test-message-attachment],[class*="event-listitem__attachment"]'
            )
          ))
          .slice(-1000)
          .map(element => {
            const body = element.querySelector(
              '[class*="event-listitem__body"],[data-test-message-body]'
            );
            const sender = element.querySelector(
              '[class*="message-group__name"],[data-test-message-sender]'
            );
            const reply = element.querySelector(
              '[data-test-message-reply],[class*="reply-to"],' +
              '[class*="quoted-message"]'
            );
            const replySender = reply?.querySelector(
              '[class*="sender"],[class*="name"],[data-test-reply-sender]'
            );
            const replyBody = reply?.querySelector(
              '[class*="body"],[class*="text"],[data-test-reply-body]'
            );
            const attachments = Array.from(element.querySelectorAll(
              '[data-test-message-attachment],[class*="message-attachment"],' +
              '[class*="event-listitem__attachment"]'
            )).slice(0, 20).map(attachment => {
              const media = attachment.matches("img,video,a")
                ? attachment
                : attachment.querySelector("img,video,a");
              const rawKind = (
                attachment.getAttribute("data-kind") ||
                media?.getAttribute("data-kind") ||
                media?.tagName ||
                ""
              ).toLowerCase();
              const name = (
                attachment.getAttribute("data-file-name") ||
                media?.getAttribute("download") ||
                attachment.innerText ||
                media?.getAttribute("alt") ||
                ""
              ).trim();
              const accessibleLabel = (
                attachment.getAttribute("aria-label") ||
                media?.getAttribute("aria-label") ||
                media?.getAttribute("alt") ||
                ""
              ).trim();
              return {
                kind: rawKind,
                name: name || null,
                accessible_label: accessibleLabel || null,
                resource_url: (
                  media?.getAttribute("href") ||
                  media?.getAttribute("src") ||
                  null
                ),
                visible_text: (
                  attachment.innerText ||
                  accessibleLabel ||
                  name
                ).trim()
              };
            });
            const reactionSummaries = Array.from(element.querySelectorAll(
              '[data-test-message-reactions],[class*="reactions-summary"],' +
              '[class*="reaction-count"]'
            )).filter(node => node.getClientRects().length > 0)
              .map(node => (
                node.getAttribute("aria-label") ||
                node.innerText ||
                ""
              ).trim())
              .filter(Boolean)
              .slice(0, 20);
            const descendantClasses = Array.from(element.querySelectorAll("*"))
              .flatMap(node => String(node.className || "").split(/\\s+/))
              .filter(Boolean)
              .join(" ");
            const visibleLines = (element.innerText || "")
              .split(/\\n/)
              .map(value => value.trim())
              .filter(Boolean);
            return {
              visible_text: element.innerText?.trim() ?? "",
              text: body?.innerText?.trim() ?? null,
              attachments,
              sender: sender?.innerText?.trim() ?? null,
              time: element.querySelector("time")?.innerText?.trim() ?? null,
              class_name: [
                element.className?.toString() ?? "",
                descendantClasses
              ].join(" "),
              direction: element.getAttribute("data-direction"),
              aria_label: element.getAttribute("aria-label"),
              edited: visibleLines.some(line => /^edited$/i.test(line)),
              reply_sender: replySender?.innerText?.trim() ?? null,
              reply_text: replyBody?.innerText?.trim() ?? (
                reply?.innerText?.trim() || null
              ),
              reaction_summaries: reactionSummaries
            };
          })
        """
    )
    return [
        cast(dict[str, object], item) for item in cast(list[object], raw) if isinstance(item, dict)
    ]


async def _history_scroller(root: Locator) -> Locator | None:
    candidates = root.locator(
        '[class*="msg-s-message-list"][class*="scrollable"],[aria-label*="message history" i]'
    )
    visible: list[Locator] = []
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        if not await candidate.is_visible():
            continue
        state = cast(
            dict[str, object],
            await candidate.evaluate(
                """
                element => ({
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight
                })
                """
            ),
        )
        if state.get("scrollHeight") != state.get("clientHeight"):
            visible.append(candidate)
    if len(visible) > 1:
        raise ParserDriftError(
            "LinkedIn Messaging exposed multiple visible conversation-history scrollers."
        )
    return visible[0] if visible else None


async def _history_signature(root: Locator) -> tuple[str, ...]:
    identities: list[str] = []
    for item in await _raw_messages(root):
        values = tuple(
            value
            for key in ("visible_text", "sender", "time", "class_name")
            if isinstance((value := item.get(key)), str) and value
        )
        if values:
            identities.append(hashlib.sha256("\x1f".join(values).encode()).hexdigest())
    scroller = await _history_scroller(root)
    if scroller is not None:
        state = cast(
            dict[str, object],
            await scroller.evaluate(
                """
                element => ({
                  scrollTop: Math.round(element.scrollTop),
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight
                })
                """
            ),
        )
        identities.append(
            "scroll:"
            + ":".join(
                str(state.get(key, "")) for key in ("scrollTop", "scrollHeight", "clientHeight")
            )
        )
    return tuple(identities)


async def _history_at_physical_start(root: Locator) -> bool:
    scroller = await _history_scroller(root)
    if scroller is None:
        return True
    state = cast(
        dict[str, object],
        await scroller.evaluate(
            """
            element => ({
              scrollTop: element.scrollTop,
              scrollHeight: element.scrollHeight,
              clientHeight: element.clientHeight,
              flexDirection: getComputedStyle(element).flexDirection
            })
            """
        ),
    )
    scroll_top = state.get("scrollTop")
    scroll_height = state.get("scrollHeight")
    client_height = state.get("clientHeight")
    flex_direction = state.get("flexDirection")
    if not (
        isinstance(scroll_top, int | float)
        and isinstance(scroll_height, int | float)
        and isinstance(client_height, int | float)
    ):
        raise ParserDriftError("LinkedIn's conversation-history scroll state is invalid.")
    boundary = max(0.0, scroll_height - client_height)
    if flex_direction == "column-reverse":
        return abs(scroll_top) >= boundary - 2
    return scroll_top <= 2


def _history_has_explicit_start(visible_text: str) -> bool:
    return any(
        re.fullmatch(
            r"(?:you(?:'|\N{RIGHT SINGLE QUOTATION MARK})?ve reached the beginning|"
            r"beginning of (?:the )?conversation|no older messages)",
            line,
            re.I,
        )
        for line in _lines(visible_text)
    )


async def _settle_history_scroll(
    paced: Paced,
    page: Page,
    root: Locator,
) -> CollectionSettleResult:
    baseline = await _history_signature(root)
    scroller = await _history_scroller(root)
    if scroller is None:
        return CollectionSettleResult(
            outcome=CollectionSettleOutcome.EXPLICIT_END,
            signature=baseline,
        )
    box = await scroller.bounding_box()
    if box is None:
        raise ParserDriftError("LinkedIn's conversation-history scroller is not visible.")
    delivery_attempt = 0

    async def scroll() -> None:
        nonlocal delivery_attempt
        delivery_attempt += 1
        await paced.hover(
            scroller,
            position={
                "x": box["width"] / 2,
                "y": min(20, box["height"] / 2),
            },
        )
        await paced.wheel(page.mouse, 0, -1_800)
        await paced.evaluate(
            scroller,
            """
            element => {
              const boundary = Math.max(0, element.scrollHeight - element.clientHeight);
              element.scrollTop = getComputedStyle(element).flexDirection === "column-reverse"
                ? -boundary
                : 0;
            }
            """,
        )
        if delivery_attempt > 1:
            await dispatch_bubbling_wheel(paced, scroller, delta_y=-1_800)

    async def explicit_start() -> bool:
        return _history_has_explicit_start(await _visible_text(root))

    return await wait_for_collection_interaction(
        page,
        baseline=baseline,
        interact=scroll,
        read_signature=lambda: _history_signature(root),
        read_explicit_end=explicit_start,
        attempts=_SCROLL_PROGRESS_POLL_ATTEMPTS,
        delay_ms=_SCROLL_PROGRESS_POLL_DELAY_MS,
    )


class ConversationGetPage(ConversationSurface):
    async def read(self, request: ConversationGetInput) -> ConversationObservation:
        async with self._browser.page() as page:
            page, root, profile_slug, name, is_group = await self._open(
                page,
                profile_slug=request.profile_slug,
                conversation_id=request.conversation_id,
                conversation_ref=request.conversation_ref,
            )
            return await self._extract(
                page,
                root,
                conversation_ref=request.conversation_ref,
                profile_slug=profile_slug,
                participant_name=name,
                is_group=is_group,
                max_messages=request.max_messages,
            )

    async def _extract(
        self,
        page: Page,
        root: Locator,
        *,
        conversation_ref: str | None,
        profile_slug: str | None,
        participant_name: str,
        is_group: bool,
        max_messages: int,
    ) -> ConversationObservation:
        conversation_id = conversation_id_from_url(page.url)
        target = conversation_id or profile_slug or participant_name.casefold()
        snapshots: list[tuple[SurfaceMessageObservation, ...]] = []
        captures: list[str] = []
        observed_refs: set[str] = set()
        stop_reason = StopReason.SAFETY_BOUND
        end_confirmations = 0
        rounds_visited = 0

        for round_index in range(self._max_history_rounds):
            rounds_visited += 1
            visible_text = await _visible_text(root)
            if not captures or captures[-1] != visible_text:
                captures.append(visible_text)
            snapshot = self._snapshot_messages(
                await _raw_messages(root),
                target=target,
                page_url=page.url,
                participant_name=participant_name,
                is_group=is_group,
            )
            snapshots.append(snapshot)
            observed_refs.update(message.message_ref for message in snapshot)
            if len(observed_refs) > max_messages:
                stop_reason = StopReason.RESULT_LIMIT
                break
            if _history_has_explicit_start(visible_text):
                stop_reason = (
                    StopReason.NO_NEW_RESULTS
                    if not observed_refs
                    else StopReason.VISIBLE_PAGE_COMPLETE
                )
                break
            if round_index + 1 >= self._max_history_rounds:
                break
            settled = await _settle_history_scroll(self._paced, page, root)
            if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                stop_reason = (
                    StopReason.NO_NEW_RESULTS
                    if not observed_refs
                    else StopReason.VISIBLE_PAGE_COMPLETE
                )
                break
            if settled.outcome is CollectionSettleOutcome.PROGRESSED:
                end_confirmations = 0
                continue
            if await _history_at_physical_start(root):
                end_confirmations += 1
                if end_confirmations >= _HISTORY_END_CONFIRMATION_ROUNDS:
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not observed_refs
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
            else:
                end_confirmations = 0

        merged: list[SurfaceMessageObservation] = []
        merged_refs: set[str] = set()
        for snapshot in reversed(snapshots):
            for message in snapshot:
                if message.message_ref in merged_refs:
                    continue
                merged_refs.add(message.message_ref)
                merged.append(message)
        retained = tuple(
            MessageObservation.model_validate(message.model_dump(mode="python"))
            for message in merged[-max_messages:]
        )
        history_complete = stop_reason in {
            StopReason.NO_NEW_RESULTS,
            StopReason.VISIBLE_PAGE_COMPLETE,
        }
        captured_at = datetime.now(UTC)
        evidence_text = "\n\n--- history window ---\n\n".join(captures)
        return ConversationObservation(
            conversation_ref=conversation_ref,
            conversation_id=conversation_id,
            participant_profile_slug=profile_slug,
            participant_profile_url=(
                HttpUrl(canonical_profile_url(profile_slug)) if profile_slug else None
            ),
            participant_name=participant_name,
            is_group=is_group,
            messages=retained,
            visible_text=evidence_text,
            coverage=ConversationCoverage(
                messages_observed=len(merged),
                messages_returned=len(retained),
                attachments_returned=sum(len(message.attachments) for message in retained),
                replies_returned=sum(
                    message.reply_to_sender_name is not None or message.reply_to_text is not None
                    for message in retained
                ),
                reactions_returned=sum(len(message.reaction_summaries) for message in retained),
                max_messages=max_messages,
                rounds_visited=rounds_visited,
                stop_reason=stop_reason,
                history_complete=history_complete,
                truncated=not history_complete or len(merged) > len(retained),
                captured_at=captured_at,
            ),
            captured_at=captured_at,
        )
