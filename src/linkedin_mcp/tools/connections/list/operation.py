"""Application operation for `linkedin.connections.list`."""

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
from linkedin_mcp.tools.connections.list.evidence import source_from_connections
from linkedin_mcp.tools.connections.list.models import (
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionSummary,
)


class ConnectionsListProvider(Protocol):
    async def collect(
        self,
        request: ConnectionsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConnectionSummary, ...], ConnectionsListCoverage, str, str]: ...


class ListConnectionsOperation(OperationSupport):
    _connections_list: ConnectionsListProvider

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_LIST, request)
            connections, coverage, captured_text, source_url = await self._connections_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                connections,
                key=lambda connection: connection.profile_slug,
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
            source = source_from_connections(
                source_url=source_url,
                captured_text=captured_text,
                connections=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return ConnectionsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                connections=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)
