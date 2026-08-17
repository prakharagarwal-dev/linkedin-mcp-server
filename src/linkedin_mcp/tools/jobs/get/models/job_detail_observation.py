from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    EvidenceField,
    JobId,
    StrictModel,
)
from linkedin_mcp.tools.jobs.get.models.job_apply_method import JobApplyMethod
from linkedin_mcp.tools.jobs.get.models.job_hiring_team_member import JobHiringTeamMember
from linkedin_mcp.tools.jobs.models.job_workplace_type import JobWorkplaceType


class JobDetailObservation(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    employment_type: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    applicant_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    description_text: Annotated[str, Field(min_length=1)] | None = None
    apply_method: JobApplyMethod = JobApplyMethod.UNAVAILABLE
    easy_apply: bool | None = None
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    hiring_team: tuple[JobHiringTeamMember, ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...]
    captured_at: datetime
