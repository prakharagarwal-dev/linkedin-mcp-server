"""Application operation for `linkedin.invitations.ignore`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    InvitationIgnorePayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.invitations.ignore.models.invitation_ignore_input import (
    InvitationIgnoreInput,
)


class InvitationIgnoreProvider(Protocol):
    async def inspect_ignore(self, request: InvitationIgnoreInput) -> ActionInspection: ...

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult: ...


class IgnoreInvitationOperation(OperationSupport):
    _invitation_ignore: InvitationIgnoreProvider

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_IGNORE,
            request=request,
            action_type=ActionType.INVITATION_IGNORE,
            payload_factory=lambda inspection: InvitationIgnorePayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_ignore_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_ignore.inspect_ignore(request),
            perform=self._invitation_ignore.perform_ignore,
        )

    @staticmethod
    def _missing_ignore_invitation_reference() -> str:
        raise RuntimeError("Invitation inspection did not return an invitation reference.")
