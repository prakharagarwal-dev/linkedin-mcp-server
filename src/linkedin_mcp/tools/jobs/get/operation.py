"""Application operation for `linkedin.jobs.get`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools.jobs.get.evidence import source_from_job_detail
from linkedin_mcp.tools.jobs.get.models import (
    JobDetailInput,
    JobDetailObservation,
    JobDetailOutput,
)


class JobDetailProvider(Protocol):
    async def read(self, request: JobDetailInput) -> JobDetailObservation: ...


class GetJobOperation(OperationSupport):
    _job_detail: JobDetailProvider

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        job = await self._job_detail.read(request)
        source = source_from_job_detail(job)
        return JobDetailOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            job=job,
            sources=(source,),
        )
