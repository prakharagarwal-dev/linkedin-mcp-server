from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.jobs.search.models.job_search_coverage import JobSearchCoverage
from linkedin_mcp.tools.jobs.search.models.job_summary import JobSummary


class JobSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    jobs: tuple[JobSummary, ...]
    coverage: JobSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
