"""Pagination and output construction for `linkedin.connections.list`."""

from __future__ import annotations

from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.connections.list.evidence import source_from_connections
from linkedin_mcp.tools.connections.list.models.connections_list_input import ConnectionsListInput
from linkedin_mcp.tools.connections.list.models.connections_list_output import ConnectionsListOutput
from linkedin_mcp.tools.connections.list.page import ConnectionsListPage
from linkedin_mcp.transport.context import current_client_id


async def execute(
    request: ConnectionsListInput,
    *,
    page: ConnectionsListPage,
    pagination: PaginationManager,
    account_id: str,
) -> ConnectionsListOutput:
    state = await pagination.start(
        account_id=account_id,
        client_id=current_client_id(),
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=request,
    )
    connections, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        connections,
        key=lambda connection: connection.profile_slug,
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
    source = source_from_connections(
        source_url=source_url,
        captured_text=captured_text,
        connections=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    return ConnectionsListOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        connections=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
