"""Application operation for `linkedin.invitations.send`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    InvitationSendPayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.invitations.send.models.invitation_send_input import InvitationSendInput


class InvitationSendProvider(Protocol):
    async def inspect_send(self, request: InvitationSendInput) -> ActionInspection: ...

    async def perform_send(self, command: ActionCommand) -> ActionPageResult: ...


class SendInvitationOperation(OperationSupport):
    _invitation_send: InvitationSendProvider

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_SEND,
            request=request,
            action_type=ActionType.INVITATION_SEND,
            payload=InvitationSendPayload(note=request.note),
            inspect=lambda: self._invitation_send.inspect_send(request),
            perform=self._invitation_send.perform_send,
        )
