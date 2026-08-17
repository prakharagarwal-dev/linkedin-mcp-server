"""Visible LinkedIn page implementation for `linkedin_mcp.tools.invitations.send.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, LinkedInMCPError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    InvitationSendPayload,
)
from linkedin_mcp.tools._shared.network_models import (
    InvitationSendInput,
)
from linkedin_mcp.tools._shared.urls import canonical_profile_url
from linkedin_mcp.tools.invitations.action_surface import InvitationActionSurface


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        value = (await locator.first.inner_text()).strip()
        if value:
            return value
    raise ParserDriftError("LinkedIn returned no visible connection text.")


async def _wait_for_unique_visible(
    page: Page,
    locator: Locator,
    description: str,
    *,
    attempts: int = 20,
) -> Locator:
    for _ in range(attempts):
        visible = [
            locator.nth(index)
            for index in range(await locator.count())
            if await locator.nth(index).is_visible()
        ]
        if len(visible) == 1:
            return visible[0]
        if len(visible) > 1:
            raise ParserDriftError(f"LinkedIn exposed ambiguous visible {description}.")
        await page.wait_for_timeout(250)
    raise ParserDriftError(f"LinkedIn exposed no unique visible {description}.")


class SendInvitationPage(InvitationActionSurface):
    async def inspect_send(
        self,
        request: InvitationSendInput,
    ) -> ActionInspection:
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(request.profile_slug))
            main, name = await self._profile_identity(page)
            state, connect = await self._wait_for_connect_control(page, main, name)
            if state != "connect_available":
                raise InvalidTargetError(
                    f"LinkedIn profile is not eligible for a new invitation: {state}."
                )
            if connect is None:
                raise ParserDriftError("The exact profile has no unique visible Connect control.")
            await self._browser.click_visible_control(page, connect)
            dialog = await _wait_for_unique_visible(
                page,
                page.get_by_role("dialog"),
                "invitation confirmation dialog",
            )
            dialog = await self._validate_invitation_dialog(
                page,
                dialog,
                request.note,
            )
            captured_text = f"{await _visible_text(page)}\n{await dialog.inner_text()}".strip()
            return ActionInspection(
                target=ActionTarget(
                    profile_slug=request.profile_slug,
                    profile_url=HttpUrl(canonical_profile_url(request.profile_slug)),
                    display_name=name,
                ),
                current_state=state,
                source_url=HttpUrl(page.url),
                captured_text=captured_text,
                captured_at=datetime.now(UTC),
            )

    async def _validate_invitation_dialog(
        self,
        page: Page,
        dialog: Locator,
        note: str | None,
    ) -> Locator:
        if re.search(r"how do you know", await dialog.inner_text(), re.I):
            raise InvalidTargetError(
                "LinkedIn requires a relationship choice; no relationship was inferred."
            )
        if note is None:
            send_without_note = dialog.get_by_role(
                "button",
                name=re.compile(r"^send without a note$", re.I),
            )
            if await send_without_note.count() != 1:
                raise ParserDriftError(
                    "The current invitation dialog has no unique Send without a note control."
                )
            await self._validate_send_control(send_without_note)
            return dialog

        add_note = dialog.get_by_role("button", name=re.compile(r"^add a note$", re.I))
        if await add_note.count() != 1:
            raise InvalidTargetError(
                "LinkedIn does not offer a personalized note for this invitation."
            )
        await self._browser.click_visible_control(page, add_note)
        textbox = await _wait_for_unique_visible(
            page,
            page.get_by_role("dialog").get_by_role("textbox"),
            "invitation note textbox",
        )
        note_dialog = textbox.locator("xpath=ancestor::*[self::dialog or @role='dialog'][1]")
        if await note_dialog.count() != 1 or not await note_dialog.is_visible():
            raise ParserDriftError("Invitation note textbox has no unique visible dialog.")
        maximum = await self._invitation_note_limit(textbox, note_dialog)
        if len(note) > maximum:
            raise InvalidTargetError(
                "The invitation note exceeds LinkedIn's current visible field limit."
            )
        await textbox.fill(note)
        note_count, note_limit = await self._invitation_note_counter(note_dialog)
        if await textbox.input_value() != note or note_count != len(note) or note_limit != maximum:
            raise ParserDriftError(
                "The invitation note did not visibly commit to the textbox and character counter."
            )
        send = note_dialog.get_by_role(
            "button",
            name=re.compile(r"^send invitation$", re.I),
        )
        if await send.count() != 1:
            raise ParserDriftError("The current note dialog has no unique Send invitation control.")
        await self._validate_send_control(send)
        return note_dialog

    @staticmethod
    async def _validate_send_control(send: Locator) -> None:
        if not await send.is_visible() or not await send.is_enabled():
            raise ParserDriftError("The current invitation Send control is not actionable.")
        try:
            await send.click(trial=True, timeout=2_000)
        except PlaywrightError as error:
            raise ParserDriftError(
                "The current invitation Send control did not pass actionability checks."
            ) from error

    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationSendPayload):
            raise InvalidTargetError("The invitation action payload is invalid.")
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(command.target.profile_slug))
            main, name = await self._profile_identity(page)
            if name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    "The visible profile name changed during the action; review before retrying.",
                )
            state, connect = await self._wait_for_connect_control(page, main, name)
            if state in {"already_connected", "pending_sent"}:
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    False,
                    state,
                    "LinkedIn already shows the requested terminal connection state.",
                )
            if state != "connect_available" or connect is None:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    state,
                    "The requested profile no longer exposes a visible Connect action.",
                )
            await self._browser.click_visible_control(page, connect)
            try:
                dialog = await _wait_for_unique_visible(
                    page,
                    page.get_by_role("dialog"),
                    "invitation confirmation dialog",
                )
            except ParserDriftError:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "connection_dialog_unavailable",
                    "Connect opened no supported visible invitation confirmation.",
                )
            if re.search(r"how do you know", await dialog.inner_text(), re.I):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "relationship_confirmation_required",
                    "LinkedIn requires a relationship choice; no relationship was inferred.",
                )
            if command.payload.note:
                add_note = dialog.get_by_role("button", name=re.compile(r"^add a note$", re.I))
                if await add_note.count() != 1:
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "personalized_invitation_unavailable",
                        "LinkedIn does not offer a personalized note for this invitation.",
                    )
                await self._browser.click_visible_control(page, add_note)
                textbox = await _wait_for_unique_visible(
                    page,
                    page.get_by_role("dialog").get_by_role("textbox"),
                    "invitation note textbox",
                )
                dialog = textbox.locator("xpath=ancestor::*[self::dialog or @role='dialog'][1]")
                if await dialog.count() != 1 or not await dialog.is_visible():
                    raise ParserDriftError("Invitation note textbox has no unique visible dialog.")
                maximum = await self._invitation_note_limit(textbox, dialog)
                if len(command.payload.note) > maximum:
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "invitation_note_too_long",
                        "The requested note exceeds LinkedIn's current visible field limit.",
                    )
                await textbox.fill(command.payload.note)
                note_value = await textbox.input_value()
                note_count, note_limit = await self._invitation_note_counter(dialog)
                if (
                    note_value != command.payload.note
                    or note_count != len(command.payload.note)
                    or note_limit != maximum
                ):
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "invitation_note_not_committed",
                        (
                            "The exact requested note was not visibly committed to LinkedIn's "
                            "textbox and character counter."
                        ),
                    )
            send = dialog.get_by_role(
                "button",
                name=(
                    re.compile(r"^send invitation$", re.I)
                    if command.payload.note
                    else re.compile(r"^send without a note$", re.I)
                ),
            )
            if await send.count() != 1:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_unavailable",
                    "The visible invitation dialog has no unique supported Send control.",
                )
            if not await send.is_visible() or not await send.is_enabled():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_not_actionable",
                    "The visible Send control is disabled or not actionable.",
                )
            try:
                await send.click(trial=True, timeout=2_000)
            except PlaywrightError:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_not_actionable",
                    "The visible Send control did not pass Playwright's actionability checks.",
                )
            verification_source_url = HttpUrl(page.url)
            verification_captured_text = (
                f"{await _visible_text(page)}\n{await dialog.inner_text()}".strip()
            )
            verification_captured_at = datetime.now(UTC)
            try:
                await self._browser.click_visible_control(page, send)
            except LinkedInMCPError as error:
                if error.pause_required:
                    raise
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    (
                        "The final Send click did not complete, so its outcome could not be "
                        f"verified: {error.safe_message}"
                    ),
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            except Exception:
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The final Send click did not complete, so its outcome could not be verified.",
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            try:
                await self._browser.navigate(
                    page,
                    canonical_profile_url(command.target.profile_slug),
                )
                main, fresh_name = await self._profile_identity(page)
                state, _ = await self._wait_for_connect_control(page, main, fresh_name)
            except LinkedInMCPError as error:
                if error.pause_required:
                    raise
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    (
                        "The final Send click completed, but the fresh profile verification "
                        f"failed: {error.safe_message}"
                    ),
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            except Exception:
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The final Send click completed, but the fresh profile could not be read.",
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            if fresh_name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The fresh profile identity did not match the requested invitation target.",
                )
            if state == "pending_sent":
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "pending_sent",
                    "A fresh exact-profile read visibly shows the invitation as Pending.",
                )
            if state == "connect_available":
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_not_sent",
                    (
                        "The fresh exact-profile read still shows Connect, so LinkedIn did not "
                        "send the invitation."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "invitation_outcome_unknown",
                (
                    "The fresh exact-profile read showed neither Pending nor a visible Connect "
                    f"action; the observed state was {state}."
                ),
            )

    @staticmethod
    async def _invitation_note_limit(textbox: Locator, dialog: Locator) -> int:
        limits: set[int] = set()
        maximum = await textbox.get_attribute("maxlength")
        if maximum is not None:
            try:
                limits.add(int(maximum))
            except ValueError as error:
                raise ParserDriftError(
                    "LinkedIn exposed an invalid invitation-note maxlength."
                ) from error
        for match in re.finditer(r"\b\d+\s*/\s*(?P<maximum>\d+)\b", await dialog.inner_text()):
            limits.add(int(match.group("maximum")))
        if len(limits) != 1:
            raise ParserDriftError(
                "LinkedIn exposed no unique visible invitation-note character limit."
            )
        return limits.pop()

    @staticmethod
    async def _invitation_note_counter(dialog: Locator) -> tuple[int, int]:
        counters = {
            (int(match.group("current")), int(match.group("maximum")))
            for match in re.finditer(
                r"\b(?P<current>\d+)\s*/\s*(?P<maximum>\d+)\b",
                await dialog.inner_text(),
            )
        }
        if len(counters) != 1:
            raise ParserDriftError(
                "LinkedIn exposed no unique visible invitation-note character counter."
            )
        return counters.pop()

    @staticmethod
    def _captured_result(
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
        *,
        source_url: HttpUrl,
        captured_text: str,
        captured_at: datetime,
    ) -> ActionPageResult:
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=source_url,
            captured_text=captured_text,
            captured_at=captured_at,
        )
