from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    StrictModel,
)


class CompanySummary(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
