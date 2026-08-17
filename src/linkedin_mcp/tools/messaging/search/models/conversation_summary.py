from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints

from linkedin_mcp.tools._shared.models import (
    ConversationId,
    ProfileSlug,
    StrictModel,
)


class ConversationSummary(StrictModel):
    conversation_ref: Annotated[
        str,
        StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$"),
    ]
    conversation_id: ConversationId | None = None
    participant_profile_slug: ProfileSlug | None = None
    participant_profile_url: HttpUrl | None = None
    participant_name: Annotated[str, Field(min_length=1, max_length=500)]
    is_group: bool = False
    last_message_text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    last_activity_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    unread: bool
    starred: bool = False
    muted: bool = False
    labels: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=200)], ...],
        Field(max_length=10),
    ] = ()
    visible_text: Annotated[str, Field(min_length=1)]
