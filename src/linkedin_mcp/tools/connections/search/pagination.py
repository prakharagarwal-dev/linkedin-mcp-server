"""Pagination and output construction for `linkedin.connections.search`."""

from __future__ import annotations

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.mcp.context import current_client_id
from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.connections.search.evidence import source_from_people_search
from linkedin_mcp.tools.connections.search.models.connections_search_input import (
    ConnectionsSearchInput,
)
from linkedin_mcp.tools.connections.search.models.connections_search_output import (
    ConnectionsSearchOutput,
)
from linkedin_mcp.tools.connections.search.page import ConnectionsSearchPage
from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree


async def execute(
    request: ConnectionsSearchInput,
    *,
    page: ConnectionsSearchPage,
    pagination: PaginationManager,
    account_id: str,
) -> ConnectionsSearchOutput:
    state = await pagination.start(
        account_id=account_id,
        client_id=current_client_id(),
        capability_name=CapabilityName.CONNECTIONS_SEARCH,
        request=request,
    )
    people, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
    )
    if any(person.connection_degree is not PersonConnectionDegree.FIRST for person in people):
        raise ParserDriftError(
            "LinkedIn Connections search returned a result that was not visibly first-degree."
        )
    selected = select_page(
        people,
        key=lambda person: person.profile_slug,
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
    source = source_from_people_search(
        source_url=source_url,
        captured_text=captured_text,
        people=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    return ConnectionsSearchOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        people=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
