"""Application operation for `linkedin.messaging.send`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    MessageSendPayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.messaging.send.models import MessageSendInput


class MessageSendProvider(Protocol):
    async def inspect_message(self, request: MessageSendInput) -> ActionInspection: ...

    async def perform_message(self, command: ActionCommand) -> ActionPageResult: ...


class SendMessageOperation(OperationSupport):
    _message_send: MessageSendProvider

    async def send_message(self, request: MessageSendInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.MESSAGING_SEND,
            request=request,
            action_type=ActionType.MESSAGE_SEND,
            payload=MessageSendPayload(
                message=request.message,
                attachment_refs=tuple(attachment.asset_ref for attachment in request.attachments),
                gif=request.gif,
                reply_to_message_ref=request.reply_to_message_ref,
            ),
            inspect=lambda: self._message_send.inspect_message(request),
            perform=self._message_send.perform_message,
        )
