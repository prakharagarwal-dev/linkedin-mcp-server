from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.search.models.post_search_coverage import PostSearchCoverage
from linkedin_mcp.tools.posts.search.models.post_summary import PostSummary


class PostSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    posts: tuple[PostSummary, ...]
    coverage: PostSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
