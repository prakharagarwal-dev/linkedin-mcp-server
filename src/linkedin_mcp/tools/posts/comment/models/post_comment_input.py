from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.comment.models.comment_attachment import CommentAttachment
from linkedin_mcp.tools.posts.models.post_mention_input import PostMentionInput


class PostCommentInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()
    attachment: CommentAttachment | None = None

    @model_validator(mode="after")
    def validate_comment_content(self) -> PostCommentInput:
        if self.text is None and self.attachment is None:
            raise ValueError("A comment requires text, a photo, or a GIF")
        if self.mentions and self.text is None:
            raise ValueError("Comment mentions require comment text")
        tokens = tuple(mention.token for mention in self.mentions)
        if len({token.casefold() for token in tokens}) != len(tokens):
            raise ValueError("Comment mention tokens must be unique")
        if self.text is not None:
            for token in tokens:
                if self.text.count(token) != 1:
                    raise ValueError(
                        "Each comment mention token must occur exactly once in comment text"
                    )
        return self
