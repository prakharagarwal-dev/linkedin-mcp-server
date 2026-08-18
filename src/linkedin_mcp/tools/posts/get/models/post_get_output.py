from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.get.models.post_observation import PostObservation


class PostGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    post: PostObservation
    sources: tuple[SourceReference, ...]
