from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    Identifier,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_target_input import (
    ConversationTargetInput,
)


class ConversationGetInput(ConversationTargetInput):
    context_id: Identifier
    request_id: Identifier
    max_messages: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description=(
                "Maximum latest messages returned after bounded traversal of LinkedIn's "
                "reverse-virtualized visible history."
            ),
        ),
    ] = 50
