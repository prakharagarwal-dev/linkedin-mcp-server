"""Models for `linkedin_mcp.tools.connections.list`."""

from __future__ import annotations

from linkedin_mcp.tools._shared.models import Identifier, PaginatedInput
from linkedin_mcp.tools.connections.list.models.connections_sort_by import ConnectionsSortBy


class ConnectionsListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED
