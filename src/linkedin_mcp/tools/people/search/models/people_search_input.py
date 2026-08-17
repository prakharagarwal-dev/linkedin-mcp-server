from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
)
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters


class PeopleSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for visible People search.",
            ),
        ]
        | None
    ) = None
    filters: PeopleSearchFilters = Field(
        default_factory=PeopleSearchFilters,
        description="Optional structured filters from LinkedIn's visible People search.",
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PeopleSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("People search requires query or at least one filter")
        return self
