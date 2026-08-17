from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    Identifier,
    JobId,
    StrictModel,
)


class JobDetailInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    job_id: JobId
