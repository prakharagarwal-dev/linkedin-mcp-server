"""Application operation for `linkedin.companies.search`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.app.pagination import (
    PaginationLease,
    select_page,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.companies.search.evidence import source_from_company_search
from linkedin_mcp.tools.companies.search.models.company_search_coverage import CompanySearchCoverage
from linkedin_mcp.tools.companies.search.models.company_search_input import CompanySearchInput
from linkedin_mcp.tools.companies.search.models.company_search_output import CompanySearchOutput
from linkedin_mcp.tools.companies.search.models.company_summary import CompanySummary


class CompanySearchProvider(Protocol):
    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]: ...


class SearchCompaniesOperation(OperationSupport):
    _company_search: CompanySearchProvider

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.COMPANIES_SEARCH, request)
            companies, coverage, captured_text, source_url = await self._company_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                companies,
                key=lambda company: company.company_slug,
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
            source = source_from_company_search(
                source_url=source_url,
                captured_text=captured_text,
                companies=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return CompanySearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                companies=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)
