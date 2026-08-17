"""Capability-owned exports from `linkedin_mcp.tools._shared.network_models`."""

from linkedin_mcp.tools._shared.network_models import (
    ConnectionsSearchFilters,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
)
from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree

__all__ = [
    "ConnectionsSearchFilters",
    "ConnectionsSearchInput",
    "ConnectionsSearchOutput",
    "PersonConnectionDegree",
]
