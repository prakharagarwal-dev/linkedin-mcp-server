from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    Identifier,
    StrictModel,
)


class CompanyGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    company_slug: CompanySlug
