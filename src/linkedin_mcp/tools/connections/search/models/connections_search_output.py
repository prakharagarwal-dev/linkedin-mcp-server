"""Models for `linkedin_mcp.tools.connections.search`."""

from __future__ import annotations

from linkedin_mcp.tools.people.search.models.people_search_output import PeopleSearchOutput


class ConnectionsSearchOutput(PeopleSearchOutput):
    """People-shaped results from LinkedIn's broad Connections search entry point."""
