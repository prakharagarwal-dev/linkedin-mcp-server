from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.people.search.models.people_search_coverage import PeopleSearchCoverage
from linkedin_mcp.tools.people.search.models.person_summary import PersonSummary


class PeopleSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    people: tuple[PersonSummary, ...]
    coverage: PeopleSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
