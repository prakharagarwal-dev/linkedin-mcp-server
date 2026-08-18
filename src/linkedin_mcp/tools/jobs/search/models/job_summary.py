from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    EvidenceField,
    JobId,
    StrictModel,
)
from linkedin_mcp.tools.jobs.models.job_workplace_type import JobWorkplaceType


class JobSummary(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    easy_apply: bool = False
    verified: bool = False
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...] = ()
