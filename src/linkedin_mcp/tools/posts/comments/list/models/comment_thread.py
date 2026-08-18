from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_observation import CommentObservation


class CommentThread(StrictModel):
    comment: CommentObservation
    replies: tuple[CommentObservation, ...] = ()
