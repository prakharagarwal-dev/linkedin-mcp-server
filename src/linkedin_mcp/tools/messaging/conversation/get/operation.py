"""Application operation for `linkedin.messaging.conversation.get`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools.messaging.conversation.get.evidence import source_from_conversation
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_input import (
    ConversationGetInput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_output import (
    ConversationGetOutput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_observation import (
    ConversationObservation,
)


class ConversationReadProvider(Protocol):
    async def read(self, request: ConversationGetInput) -> ConversationObservation: ...


class GetConversationOperation(OperationSupport):
    _conversation_read: ConversationReadProvider

    async def get_conversation(
        self,
        request: ConversationGetInput,
    ) -> ConversationGetOutput:
        observation = await self._conversation_read.read(request)
        source = source_from_conversation(observation)
        return ConversationGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            conversation=observation,
            sources=(source,),
        )
