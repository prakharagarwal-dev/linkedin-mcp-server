"""Visible LinkedIn page implementation for `linkedin_mcp.tools.invitations.accept.page`."""

from __future__ import annotations

import hashlib

from linkedin_mcp.errors import InvalidTargetError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    InvitationAcceptPayload,
)
from linkedin_mcp.tools.invitations.accept.models.invitation_accept_input import (
    InvitationAcceptInput,
)
from linkedin_mcp.tools.invitations.action_surface import InvitationActionSurface
from linkedin_mcp.ui.urls import canonical_profile_url


def _received_invitation_ref(profile_slug: str) -> str:
    digest = hashlib.sha256(f"received\x1f{profile_slug}".encode()).hexdigest()[:24]
    return f"invitation:{digest}"


class AcceptInvitationPage(InvitationActionSurface):
    async def inspect_accept(
        self,
        request: InvitationAcceptInput,
    ) -> ActionInspection:
        return await self._inspect_received_request(request.profile_slug)

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationAcceptPayload):
            raise InvalidTargetError("The acceptance action payload is invalid.")
        expected_ref = _received_invitation_ref(command.target.profile_slug)
        if command.payload.invitation_ref != expected_ref:
            raise InvalidTargetError("The acceptance payload does not match the target invitation.")
        async with self._playwright.page() as page:
            await page.goto(canonical_profile_url(command.target.profile_slug))
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
                state, _ = await self._wait_for_connect_control(page, main, name)
                if state == "already_connected":
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        False,
                        "already_connected",
                        "The exact profile already visibly shows a first-degree connection.",
                    )
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_no_longer_pending",
                    "The exact profile no longer exposes the requested incoming request.",
                )
            try:
                await accept.click()
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "acceptance_outcome_unknown",
                    "Accept was invoked, but LinkedIn's result could not be verified.",
                )
            for _ in range(20):
                current_accept, current_ignore = await self._incoming_request_controls(main, name)
                state, _ = await self._connect_control(page, main, name)
                if (
                    current_accept is None
                    and current_ignore is None
                    and state == "already_connected"
                ):
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        "connected",
                        (
                            "The exact profile removed the incoming-request controls and "
                            "visibly shows a first-degree connection."
                        ),
                    )
                await page.wait_for_timeout(250)
            await page.goto(canonical_profile_url(command.target.profile_slug))
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
                and state == "already_connected"
            ):
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "connected",
                    (
                        "A fresh exact-profile read shows no incoming-request controls "
                        "and visibly proves a first-degree connection."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "acceptance_outcome_unknown",
                (
                    "Accept was invoked, but a fresh exact-profile read did not visibly prove "
                    "both request removal and the first-degree connection state."
                ),
            )
