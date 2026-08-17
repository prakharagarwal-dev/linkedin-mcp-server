from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_observation import (
    ConversationObservation,
)


class ConversationGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    conversation: ConversationObservation
    sources: tuple[SourceReference, ...]
