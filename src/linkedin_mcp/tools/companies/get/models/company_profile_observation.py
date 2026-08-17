from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    StrictModel,
)
from linkedin_mcp.tools.companies.get.models.company_profile_coverage import CompanyProfileCoverage
from linkedin_mcp.tools.companies.get.models.company_profile_evidence import CompanyProfileEvidence


class CompanyProfileObservation(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    website_url: HttpUrl | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_size_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    headquarters: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization_type: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    founded_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    specialties: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[CompanyProfileEvidence, ...]
    coverage: CompanyProfileCoverage
    captured_at: datetime
