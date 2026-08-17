from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
)
from linkedin_mcp.tools.posts.search.models.post_search_filters import PostSearchFilters


class PostSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PostSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Post search requires query or at least one substantive filter")
        return self
