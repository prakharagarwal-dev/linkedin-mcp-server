from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.companies.search.models.company_search_coverage import CompanySearchCoverage
from linkedin_mcp.tools.companies.search.models.company_summary import CompanySummary


class CompanySearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    companies: tuple[CompanySummary, ...]
    coverage: CompanySearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
