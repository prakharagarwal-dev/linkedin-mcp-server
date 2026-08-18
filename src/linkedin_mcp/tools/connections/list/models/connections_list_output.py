"""Models for `linkedin_mcp.tools.connections.list`."""

from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.connections.list.models.connection_summary import ConnectionSummary
from linkedin_mcp.tools.connections.list.models.connections_list_coverage import (
    ConnectionsListCoverage,
)


class ConnectionsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    connections: tuple[ConnectionSummary, ...]
    coverage: ConnectionsListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
