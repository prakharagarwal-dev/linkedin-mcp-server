"""Visible LinkedIn page implementation for `linkedin_mcp.tools.invitations.ignore.page`."""

from __future__ import annotations

import hashlib

from linkedin_mcp.errors import InvalidTargetError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    InvitationIgnorePayload,
)
from linkedin_mcp.tools._shared.urls import canonical_profile_url
from linkedin_mcp.tools.invitations.action_surface import InvitationActionSurface
from linkedin_mcp.tools.invitations.ignore.models.invitation_ignore_input import (
    InvitationIgnoreInput,
)


def _received_invitation_ref(profile_slug: str) -> str:
    digest = hashlib.sha256(f"received\x1f{profile_slug}".encode()).hexdigest()[:24]
    return f"invitation:{digest}"


class IgnoreInvitationPage(InvitationActionSurface):
    async def inspect_ignore(
        self,
        request: InvitationIgnoreInput,
    ) -> ActionInspection:
        return await self._inspect_received_request(request.profile_slug)

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationIgnorePayload):
            raise InvalidTargetError("The ignore action payload is invalid.")
        expected_ref = _received_invitation_ref(command.target.profile_slug)
        if command.payload.invitation_ref != expected_ref:
            raise InvalidTargetError("The ignore payload does not match the target invitation.")
        async with self._browser.page() as page:
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, name = await self._profile_identity(page)
            if name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    "The exact profile name changed after inspection.",
                )
            accept, ignore = await self._incoming_request_controls(main, name)
            if accept is None or ignore is None:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_no_longer_pending",
                    "The exact profile no longer exposes the requested incoming request.",
                )
            try:
                await self._browser.click_visible_control(page, ignore)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "ignore_outcome_unknown",
                    "Ignore was invoked, but LinkedIn's result could not be verified.",
                )
            for _ in range(20):
                current_accept, current_ignore = await self._incoming_request_controls(main, name)
                if current_accept is None and current_ignore is None:
                    break
                await page.wait_for_timeout(250)
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, visible_name = await self._profile_identity(page)
            current_accept, current_ignore = await self._incoming_request_controls(
                main,
                visible_name,
            )
            state, _ = await self._wait_for_connect_control(page, main, visible_name)
            if (
                visible_name.casefold() == command.target.display_name.casefold()
                and current_accept is None
                and current_ignore is None
                and state not in {"already_connected", "pending_sent"}
            ):
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "invitation_ignored",
                    (
                        "A fresh exact-profile read shows the incoming-request controls "
                        "are gone with neither a connection nor an outgoing request."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "ignore_outcome_unknown",
                (
                    "Ignore was invoked, but a fresh exact-profile read did not visibly prove "
                    "request removal without creating a connection."
                ),
            )
