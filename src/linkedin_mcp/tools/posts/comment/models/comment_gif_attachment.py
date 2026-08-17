from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_type import (
    CommentAttachmentType,
)


class CommentGifAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.GIF] = CommentAttachmentType.GIF
    search_query: Annotated[str, Field(min_length=1, max_length=200)]
    visible_result_label: Annotated[str, Field(min_length=1, max_length=500)]
