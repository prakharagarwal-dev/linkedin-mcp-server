from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.companies.search.models.company_search_filters import CompanySearchFilters


class CompanySearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime
