from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.jobs.get.models.job_detail_observation import JobDetailObservation


class JobDetailOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    job: JobDetailObservation
    sources: tuple[SourceReference, ...]
