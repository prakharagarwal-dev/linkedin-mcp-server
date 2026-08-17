from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
    PostReference,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort


class PostCommentsListInput(PaginatedInput):
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum top-level comment threads returned in this page.",
        ),
    ] = 25
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    sort_by: CommentSort = CommentSort.MOST_RELEVANT
    max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25
