from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    CommentReference,
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_observation import (
    CommentAttachmentObservation,
)
from linkedin_mcp.tools.posts.models.post_author import PostAuthor


class CommentObservation(StrictModel):
    comment_ref: CommentReference
    post_ref: PostReference
    parent_comment_ref: CommentReference | None = None
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    attachments: Annotated[
        tuple[CommentAttachmentObservation, ...],
        Field(max_length=10),
    ] = ()
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    reply_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_comment_content(self) -> CommentObservation:
        if self.text is None and not self.attachments:
            raise ValueError("A comment observation requires text or a visible attachment")
        return self
