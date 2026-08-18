from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.jobs.search.models.job_search_filters import JobSearchFilters


class JobSearchCoverage(StrictModel):
    query: str | None
    location: str | None
    freshness_hours: Literal[24, 168, 720] | None
    filters: JobSearchFilters = Field(default_factory=JobSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    advertised_result_count: Annotated[int, Field(ge=0)] | None = None
    advertised_result_count_is_lower_bound: bool = False
    captured_at: datetime
