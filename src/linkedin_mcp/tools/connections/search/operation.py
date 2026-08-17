"""Application operation for `linkedin.connections.search`."""

from __future__ import annotations

from linkedin_mcp.app.pagination import (
    PaginationLease,
    select_page,
)
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.connections.search.evidence import source_from_people_search
from linkedin_mcp.tools.connections.search.models import (
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    PersonConnectionDegree,
)
from linkedin_mcp.tools.people.search.operation import PeopleSearchProvider


class SearchConnectionsOperation(OperationSupport):
    _people_search: PeopleSearchProvider

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_SEARCH, request)
            people_request = request.as_people_search_input()
            people, coverage, captured_text, source_url = await self._people_search.collect(
                people_request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            if any(
                person.connection_degree is not PersonConnectionDegree.FIRST for person in people
            ):
                raise ParserDriftError(
                    "LinkedIn Connections search returned a result that was not visibly "
                    "first-degree."
                )
            page = select_page(
                people,
                key=lambda person: person.profile_slug,
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
            source = source_from_people_search(
                source_url=source_url,
                captured_text=captured_text,
                people=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return ConnectionsSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)
