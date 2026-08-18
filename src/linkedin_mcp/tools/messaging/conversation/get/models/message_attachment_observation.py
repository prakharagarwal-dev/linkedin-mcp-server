from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_attachment_kind import (
    MessageAttachmentKind,
)


class MessageAttachmentObservation(StrictModel):
    kind: MessageAttachmentKind
    name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    accessible_label: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    resource_url: HttpUrl | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> MessageAttachmentObservation:
        if self.name is None and self.accessible_label is None and self.resource_url is None:
            raise ValueError("A message attachment requires visible identity evidence")
        return self
