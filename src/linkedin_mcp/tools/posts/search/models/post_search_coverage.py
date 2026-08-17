from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.posts.search.models.post_search_filters import PostSearchFilters


class PostSearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unsupported_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Selected visible post cards omitted because their stable post or author "
            "identity is outside the typed public contract."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime
