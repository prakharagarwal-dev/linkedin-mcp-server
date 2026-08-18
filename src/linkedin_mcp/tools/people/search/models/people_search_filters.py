from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools.people.search.models.people_search_connection_degree import (
    PeopleSearchConnectionDegree,
)
from linkedin_mcp.tools.people.search.models.people_search_filter_base import PeopleSearchFilterBase


class PeopleSearchFilters(PeopleSearchFilterBase):
    """All-network filters from LinkedIn's current visible People-filter side panel."""

    connection_degrees: Annotated[
        tuple[PeopleSearchConnectionDegree, ...],
        Field(max_length=3),
    ] = Field(
        default=(),
        description="First-, second-, and/or third-plus-degree visible network filters.",
    )

    @model_validator(mode="after")
    def reject_duplicate_degrees(self) -> PeopleSearchFilters:
        if len(set(self.connection_degrees)) != len(self.connection_degrees):
            raise ValueError("connection_degrees cannot contain duplicate values")
        return self
