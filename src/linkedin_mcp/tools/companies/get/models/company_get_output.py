from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.companies.get.models.company_profile_observation import (
    CompanyProfileObservation,
)


class CompanyGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    company: CompanyProfileObservation
    sources: tuple[SourceReference, ...]
