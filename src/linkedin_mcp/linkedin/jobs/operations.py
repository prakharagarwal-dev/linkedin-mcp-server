"""Application operations for LinkedIn jobs."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.app.pagination import PaginationLease, select_page
from linkedin_mcp.linkedin.common import CapabilityName, StopReason
from linkedin_mcp.linkedin.execution import OperationSupport
from linkedin_mcp.linkedin.jobs.evidence import (
    source_from_job_detail,
    source_from_job_search,
)
from linkedin_mcp.linkedin.jobs.models import (
    JobDetailInput,
    JobDetailObservation,
    JobDetailOutput,
    JobSearchCoverage,
    JobSearchInput,
    JobSearchOutput,
    JobSummary,
)


class JobSearchProvider(Protocol):
    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]: ...


class JobDetailProvider(Protocol):
    async def read(self, request: JobDetailInput) -> JobDetailObservation: ...


class JobsOperations(OperationSupport):
    _job_search: JobSearchProvider
    _job_detail: JobDetailProvider

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.JOBS_SEARCH, request)
            jobs, coverage, captured_text, source_url = await self._job_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                jobs,
                key=lambda job: job.job_id,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_job_search(
                source_url=source_url,
                captured_text=captured_text,
                jobs=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return JobSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                jobs=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        job = await self._job_detail.read(request)
        source = source_from_job_detail(job)
        return JobDetailOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            job=job,
            sources=(source,),
        )
