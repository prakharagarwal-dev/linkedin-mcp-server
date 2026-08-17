from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort


class PostCommentsCoverage(StrictModel):
    post_ref: PostReference
    discussion_post_ref: PostReference
    sort_by: CommentSort
    expansion_rounds: Annotated[int, Field(ge=0)]
    top_level_visible: Annotated[int, Field(ge=0)]
    top_level_returned: Annotated[int, Field(ge=0)]
    replies_visible: Annotated[int, Field(ge=0)]
    replies_returned: Annotated[int, Field(ge=0)]
    max_comments: Annotated[int, Field(ge=1)]
    max_replies_per_comment: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime
