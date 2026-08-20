"""Pagination and output construction for `linkedin.jobs.search`."""

from __future__ import annotations

from dataclasses import asdict

from linkedin_mcp.infra.cursor import (
    CursorStore,
    cursor_binding,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    PaginationMetadata,
    StopReason,
)
from linkedin_mcp.tools.jobs.search.evidence import source_from_job_search
from linkedin_mcp.tools.jobs.search.models.job_search_input import JobSearchInput
from linkedin_mcp.tools.jobs.search.models.job_search_output import JobSearchOutput
from linkedin_mcp.tools.jobs.search.page import JobSearchPage


async def execute(
    request: JobSearchInput,
    *,
    page: JobSearchPage,
    cursor_store: CursorStore,
    account_id: str,
) -> JobSearchOutput:
    arguments = request.model_dump(
        mode="json",
        exclude={"context_id", "request_id", "cursor", "page_size"},
    )
    operation = CapabilityName.JOBS_SEARCH.value
    state = await cursor_store.start(
        account_id=account_id,
        operation=operation,
        binding=cursor_binding(operation, arguments),
        cursor=request.cursor,
    )
    jobs, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=cursor_store.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        jobs,
        key=lambda job: job.job_id,
        seen_keys=state.seen_keys,
        page_size=cursor_store.page_capacity(state, request.page_size),
    )
    provider_has_more = selected.has_lookahead or coverage.stop_reason in {
        StopReason.RESULT_LIMIT,
        StopReason.SAFETY_BOUND,
    }
    page_coverage = coverage.model_copy(
        update={
            "result_count": len(selected.items),
            "max_results": request.page_size,
            "stop_reason": (StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason),
        }
    )
    source = source_from_job_search(
        source_url=source_url,
        captured_text=captured_text,
        jobs=selected.items,
        coverage=page_coverage,
    )
    cursor_page = await cursor_store.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    metadata = PaginationMetadata.model_validate(asdict(cursor_page))
    return JobSearchOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        jobs=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
