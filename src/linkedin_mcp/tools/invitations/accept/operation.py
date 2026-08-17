"""Application operation for `linkedin.invitations.accept`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    InvitationAcceptPayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.invitations.accept.models import InvitationAcceptInput


class InvitationAcceptProvider(Protocol):
    async def inspect_accept(self, request: InvitationAcceptInput) -> ActionInspection: ...

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult: ...


class AcceptInvitationOperation(OperationSupport):
    _invitation_accept: InvitationAcceptProvider

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_ACCEPT,
            request=request,
            action_type=ActionType.INVITATION_ACCEPT,
            payload_factory=lambda inspection: InvitationAcceptPayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_accept_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_accept.inspect_accept(request),
            perform=self._invitation_accept.perform_accept,
        )

    @staticmethod
    def _missing_accept_invitation_reference() -> str:
        raise RuntimeError("Invitation inspection did not return an invitation reference.")
