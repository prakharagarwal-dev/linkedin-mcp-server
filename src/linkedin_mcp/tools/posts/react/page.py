"""Visible LinkedIn page implementation for `linkedin_mcp.tools.posts.react.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ReactionSetPayload,
)
from linkedin_mcp.tools._shared.urls import (
    canonical_post_url,
)
from linkedin_mcp.tools.posts.engagement_surface import PostEngagementSurface
from linkedin_mcp.tools.posts.react.models.post_reaction_input import PostReactionInput
from linkedin_mcp.tools.posts.react.models.reaction_state import ReactionState

_REACTION_LABELS = {
    ReactionState.LIKE: "Like",
    ReactionState.CELEBRATE: "Celebrate",
    ReactionState.SUPPORT: "Support",
    ReactionState.LOVE: "Love",
    ReactionState.INSIGHTFUL: "Insightful",
    ReactionState.FUNNY: "Funny",
}

_REACTION_STATE_SELECTOR = "[aria-label^='Reaction button state:' i]"

_REACTION_CONTROL_SELECTOR = (
    "[data-reaction-control], "
    "button[aria-label^='Reaction button state:' i], "
    "button[aria-label^='React ' i][aria-pressed], "
    "[role='button'][tabindex='0']:has("
    "[aria-label^='Reaction button state:' i])"
)

_COMMENT_ATTACHMENT_SELECTOR = (
    "[data-comment-attachment], [data-test-comment-attachment], "
    '[class*="comments-comment-item__comment-image"], '
    '[class*="comments-comment-item__gif"], '
    '[class*="comments-comment-item__media"]'
)


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        value = (await locator.first.inner_text()).strip()
        if value:
            attachments = page.locator(_COMMENT_ATTACHMENT_SELECTOR)
            accessible: list[str] = []
            for index in range(min(await attachments.count(), 100)):
                attachment = attachments.nth(index)
                if not await attachment.is_visible():
                    continue
                media = attachment.locator("img, video, a").first
                for candidate in (
                    await attachment.get_attribute("aria-label"),
                    (await media.get_attribute("aria-label") if await media.count() else None),
                    await media.get_attribute("alt") if await media.count() else None,
                ):
                    if candidate and candidate not in value and candidate not in accessible:
                        accessible.append(candidate)
            if accessible:
                value = f"{value}\n\n--- accessible comment attachment evidence ---\n" + "\n".join(
                    accessible
                )
            return value
    raise ParserDriftError("LinkedIn returned no visible engagement text.")


class PostReactionPage(PostEngagementSurface):
    async def inspect_reaction(
        self,
        request: PostReactionInput,
    ) -> ActionInspection:
        target_url = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(page, request.post_ref)
            controls = await self._wait_for_visible_reaction_controls(target.region)
            if len(controls) != 1:
                raise ParserDriftError("LinkedIn has no unique visible reaction control.")
            existing = await self._reaction_state(target.region)
            if request.desired_reaction is not ReactionState.NONE:
                await self._reaction_option(
                    page,
                    target.region,
                    request.desired_reaction,
                )
            return ActionInspection(
                target=self._action_target(target, request.post_ref),
                current_state=f"reaction_ready:post:{existing.value}",
                source_url=HttpUrl(target_url),
                captured_text=await _visible_text(page),
                captured_at=datetime.now(UTC),
                existing_reaction=existing,
            )

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, ReactionSetPayload):
            raise InvalidTargetError("The reaction action payload is invalid.")
        payload = command.payload
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_post_url(payload.post_ref))
            target = await self._resolve_target(page, payload.post_ref)
            if not self._matches_inspected_target(command.target, target):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "engagement_target_changed",
                    "The active member or visible reaction target changed after inspection.",
                )
            controls = await self._wait_for_visible_reaction_controls(target.region)
            if len(controls) != 1:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_not_changed",
                    "The exact visible reaction control did not load before the action.",
                )
            current = await self._reaction_state(target.region)
            if current is not payload.existing_reaction:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_state_changed",
                    (
                        "The visible reaction changed during the action; invoke it again "
                        "only after review."
                    ),
                )
            if current is payload.desired_reaction:
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    False,
                    self._reaction_final_state(current),
                    "LinkedIn already shows the exact requested reaction state.",
                )
            try:
                if payload.desired_reaction is ReactionState.NONE:
                    control = await self._pressed_reaction_control(target.region, current)
                else:
                    control = await self._reaction_option(
                        page,
                        target.region,
                        payload.desired_reaction,
                    )
            except (ParserDriftError, PlaywrightError):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_not_changed",
                    (
                        "The exact visible reaction control was unavailable before "
                        "the final state-changing click."
                    ),
                )
            try:
                await self._browser.click_visible_control(page, control)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "reaction_outcome_unknown",
                    "The reaction control was invoked, but its outcome is unknown.",
                )
            for _ in range(20):
                try:
                    current = await self._reaction_state(target.region)
                except ParserDriftError:
                    await page.wait_for_timeout(250)
                    continue
                if current is payload.desired_reaction:
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        self._reaction_final_state(current),
                        "LinkedIn visibly shows the exact requested reaction state.",
                    )
                await page.wait_for_timeout(250)
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "reaction_outcome_unknown",
                "LinkedIn exposed no bounded visible reaction postcondition.",
            )

    async def _reaction_option(
        self,
        page: Page,
        region: Locator,
        desired: ReactionState,
    ) -> Locator:
        if desired is ReactionState.NONE:
            raise InvalidTargetError("Removal has no reaction-menu option.")
        controls = await self._wait_for_visible_reaction_controls(region)
        if not controls:
            fallback = region.get_by_role(
                "button",
                name=re.compile(
                    r"^(?:like|react|remove (?:like|reaction)|"
                    r"reaction button state: .+)$",
                    re.I,
                ),
            )
            controls = [
                fallback.nth(index)
                for index in range(await fallback.count())
                if await fallback.nth(index).is_visible()
            ]
        if len(controls) != 1:
            raise ParserDriftError("LinkedIn has no unique visible reaction control.")
        control = controls[0]
        await control.hover()
        option_name = re.compile(rf"^{_REACTION_LABELS[desired]}$", re.I)
        explicit = region.get_by_role(
            "button",
            name=option_name,
        ).and_(region.locator("[data-reaction-option]"))
        explicit_visible = [
            explicit.nth(index)
            for index in range(await explicit.count())
            if await explicit.nth(index).is_visible()
        ]
        if len(explicit_visible) == 1:
            return explicit_visible[0]
        if explicit_visible:
            raise ParserDriftError(
                f"LinkedIn has no unique visible {desired.value} reaction option."
            )
        # The current UI portals the six reaction buttons outside the post
        # region after hover and prefixes their accessible names with "React".
        # The trigger shares that name but retains aria-pressed, while menu
        # options do not. Wait only for one exact visible unpressed option.
        portaled_name = re.compile(
            rf"^(?:React\s+)?{re.escape(_REACTION_LABELS[desired])}$",
            re.I,
        )
        portaled = page.get_by_role("button", name=portaled_name).and_(
            page.locator("button:not([aria-pressed])")
        )
        visible: list[Locator] = []
        for attempt in range(20):
            visible = [
                portaled.nth(index)
                for index in range(await portaled.count())
                if await portaled.nth(index).is_visible()
            ]
            if len(visible) == 1:
                return visible[0]
            if attempt < 19:
                await page.wait_for_timeout(250)
        raise ParserDriftError(f"LinkedIn has no unique visible {desired.value} reaction option.")

    @staticmethod
    async def _reaction_control_state(control: Locator) -> ReactionState | None:
        state = control.locator(_REACTION_STATE_SELECTOR)
        state_control = state if await state.count() == 1 else control
        label = (await state_control.get_attribute("aria-label") or "").strip().casefold()
        if label.startswith("reaction button state:"):
            normalized = label.partition(":")[2].strip()
            if normalized == "no reaction":
                return ReactionState.NONE
            if normalized in {
                value.value for value in ReactionState if value is not ReactionState.NONE
            }:
                return ReactionState(normalized)
        match = re.fullmatch(
            r"react\s+(like|celebrate|support|love|insightful|funny)",
            label,
        )
        if match is not None:
            pressed = await control.get_attribute(
                "aria-pressed"
            ) or await state_control.get_attribute("aria-pressed")
            if pressed == "false":
                return ReactionState.NONE
            if pressed == "true":
                return ReactionState(match.group(1))
        return None

    @staticmethod
    async def _reaction_state(region: Locator) -> ReactionState:
        explicit = region.locator("[data-current-reaction]")
        for index in range(await explicit.count()):
            item = explicit.nth(index)
            if not await item.is_visible():
                continue
            value = (await item.get_attribute("data-current-reaction") or "").casefold()
            if value in {state.value for state in ReactionState}:
                return ReactionState(value)
        current_controls = await PostReactionPage._visible_reaction_controls(region)
        for item in current_controls:
            if (value := await PostReactionPage._reaction_control_state(item)) is not None:
                return value
        pressed = region.locator(
            "button[aria-pressed='true'][data-reaction-control], "
            "button[aria-pressed='true'][data-current-reaction]"
        )
        for index in range(await pressed.count()):
            item = pressed.nth(index)
            if not await item.is_visible():
                continue
            label = (
                await item.get_attribute("data-current-reaction")
                or await item.get_attribute("aria-label")
                or await item.inner_text()
            ).casefold()
            for state in ReactionState:
                if state is not ReactionState.NONE and state.value in label:
                    return state
        raise ParserDriftError("LinkedIn exposed no visible reaction state.")

    @staticmethod
    async def _pressed_reaction_control(
        region: Locator,
        current: ReactionState,
    ) -> Locator:
        if current is ReactionState.NONE:
            raise InvalidTargetError("There is no current reaction to remove.")
        control = region.locator(
            "button[data-reaction-control][aria-pressed='true'], "
            "button[data-current-reaction][aria-pressed='true']"
        )
        visible = [
            control.nth(index)
            for index in range(await control.count())
            if await control.nth(index).is_visible()
        ]
        if len(visible) == 1:
            return visible[0]
        if visible:
            raise ParserDriftError(
                "LinkedIn has no unique visible current pressed reaction control."
            )
        current_containers = await PostReactionPage._visible_reaction_controls(region)
        current_matches: list[Locator] = []
        for candidate in current_containers:
            if await PostReactionPage._reaction_control_state(candidate) is current:
                current_matches.append(candidate)
        if len(current_matches) != 1:
            raise ParserDriftError("LinkedIn has no unique visible current reaction control.")
        return current_matches[0]

    @staticmethod
    async def _visible_reaction_controls(region: Locator) -> list[Locator]:
        local = region.locator(_REACTION_CONTROL_SELECTOR)
        visible = [
            local.nth(index)
            for index in range(await local.count())
            if await local.nth(index).is_visible()
        ]
        if visible:
            return visible
        region_box = await region.bounding_box()
        if region_box is None:
            return []
        current = region.page.locator(_REACTION_CONTROL_SELECTOR)
        for index in range(await current.count()):
            candidate = current.nth(index)
            if not await candidate.is_visible():
                continue
            box = await candidate.bounding_box()
            if box is None:
                continue
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            if (
                region_box["x"] <= center_x <= region_box["x"] + region_box["width"]
                and region_box["y"] <= center_y <= region_box["y"] + region_box["height"]
            ):
                visible.append(candidate)
        return visible

    @staticmethod
    async def _wait_for_visible_reaction_controls(region: Locator) -> list[Locator]:
        for _ in range(20):
            visible = await PostReactionPage._visible_reaction_controls(region)
            if visible:
                return visible
            await region.page.wait_for_timeout(250)
        return []

    @staticmethod
    def _reaction_final_state(value: ReactionState) -> str:
        return "reaction_removed" if value is ReactionState.NONE else f"reaction_set:{value.value}"
