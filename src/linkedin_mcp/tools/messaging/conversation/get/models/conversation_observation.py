from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints

from linkedin_mcp.tools._shared.models import (
    ConversationId,
    ProfileSlug,
    StrictModel,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_coverage import (
    ConversationCoverage,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_observation import (
    MessageObservation,
)


class ConversationObservation(StrictModel):
    conversation_ref: (
        Annotated[str, StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$")] | None
    ) = None
    conversation_id: ConversationId | None = None
    participant_profile_slug: ProfileSlug | None = None
    participant_profile_url: HttpUrl | None = None
    participant_name: Annotated[str, Field(min_length=1, max_length=500)]
    is_group: bool = False
    messages: tuple[MessageObservation, ...]
    visible_text: Annotated[str, Field(min_length=1)]
    coverage: ConversationCoverage
    captured_at: datetime
