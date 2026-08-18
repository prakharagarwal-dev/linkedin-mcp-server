from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters


class PeopleSearchCoverage(StrictModel):
    query: str | None
    filters: PeopleSearchFilters = Field(default_factory=PeopleSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unidentifiable_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Visible LinkedIn Member cards omitted because LinkedIn exposed no profile identity."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime
