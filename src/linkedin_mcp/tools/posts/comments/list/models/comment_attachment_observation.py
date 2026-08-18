from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_type import (
    CommentAttachmentType,
)


class CommentAttachmentObservation(StrictModel):
    attachment_type: CommentAttachmentType
    accessible_label: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    resource_url: HttpUrl | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> CommentAttachmentObservation:
        if self.accessible_label is None and self.resource_url is None:
            raise ValueError("A comment attachment requires visible identity evidence")
        return self
