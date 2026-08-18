"""Models for `linkedin_mcp.tools.connections.search`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import Identifier, PaginatedInput
from linkedin_mcp.tools.connections.search.models.connections_search_filters import (
    ConnectionsSearchFilters,
)
from linkedin_mcp.tools.people.search.models.people_search_input import PeopleSearchInput


class ConnectionsSearchInput(PaginatedInput):
    """Search established first-degree connections through LinkedIn People search."""

    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for connection search.",
            ),
        ]
        | None
    ) = None
    filters: ConnectionsSearchFilters = Field(
        default_factory=ConnectionsSearchFilters,
        description=(
            "Optional visible People filters. First-degree connection filtering is always "
            "enforced by the server and cannot be overridden."
        ),
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> ConnectionsSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Connection search requires query or at least one filter")
        return self

    def as_people_search_input(self) -> PeopleSearchInput:
        return PeopleSearchInput(
            context_id=self.context_id,
            request_id=self.request_id,
            query=self.query,
            filters=self.filters.as_people_search_filters(),
            page_size=self.page_size,
        )
