"""Pagination and output construction for `linkedin.companies.search`."""

from __future__ import annotations

from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.companies.search.evidence import source_from_company_search
from linkedin_mcp.tools.companies.search.models.company_search_input import CompanySearchInput
from linkedin_mcp.tools.companies.search.models.company_search_output import CompanySearchOutput
from linkedin_mcp.tools.companies.search.page import CompanySearchPage


async def execute(
    request: CompanySearchInput,
    *,
    page: CompanySearchPage,
    pagination: PaginationManager,
    account_id: str,
) -> CompanySearchOutput:
    state = await pagination.start(
        account_id=account_id,
        capability_name=CapabilityName.COMPANIES_SEARCH,
        request=request,
    )
    companies, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        companies,
        key=lambda company: company.company_slug,
        seen_keys=state.seen_keys,
        page_size=pagination.page_capacity(state, request.page_size),
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
    source = source_from_company_search(
        source_url=source_url,
        captured_text=captured_text,
        companies=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    return CompanySearchOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        companies=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
