from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
)
from linkedin_mcp.tools.jobs.search.models.job_search_filters import JobSearchFilters


class JobSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Keywords or a LinkedIn Boolean query using quotes, AND, OR, and NOT.",
            ),
        ]
        | None
    ) = None
    location: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible location text such as a city, region, country, or Worldwide.",
            ),
        ]
        | None
    ) = None
    freshness_hours: Literal[24, 168, 720] | None = Field(
        default=None,
        description=(
            "LinkedIn's visible Date posted choice: 24 hours, 168 hours (past week), "
            "720 hours (past month), or null for Any time."
        ),
    )
    filters: JobSearchFilters = Field(
        default_factory=JobSearchFilters,
        description="Optional structured LinkedIn Jobs filters.",
    )

    @model_validator(mode="after")
    def validate_distance_context(self) -> JobSearchInput:
        if (
            self.filters.distance_miles is not None
            and self.location is None
            and self.filters.location_geo_id is None
        ):
            raise ValueError("distance_miles requires location or filters.location_geo_id")
        return self
