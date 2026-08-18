from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_thread import CommentThread
from linkedin_mcp.tools.posts.comments.list.models.post_comments_coverage import (
    PostCommentsCoverage,
)


class PostCommentsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    threads: tuple[CommentThread, ...]
    coverage: PostCommentsCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
