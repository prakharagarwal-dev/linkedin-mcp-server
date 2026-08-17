from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    StrictModel,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_attachment_observation import (
    MessageAttachmentObservation,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_direction import MessageDirection


class MessageObservation(StrictModel):
    message_ref: Identifier
    direction: MessageDirection
    sender_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    sent_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    attachments: Annotated[
        tuple[MessageAttachmentObservation, ...],
        Field(max_length=20),
    ] = ()
    edited: bool = False
    reply_to_sender_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    reply_to_text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    reaction_summaries: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=500)], ...],
        Field(max_length=20),
    ] = ()
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_message_content(self) -> MessageObservation:
        if self.text is None and not self.attachments:
            raise ValueError("A message observation requires text or a visible attachment")
        return self
