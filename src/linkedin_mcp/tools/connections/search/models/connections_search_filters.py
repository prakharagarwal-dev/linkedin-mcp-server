"""Models for `linkedin_mcp.tools.connections.search`."""

from __future__ import annotations

from linkedin_mcp.tools.people.search.models.people_search_connection_degree import (
    PeopleSearchConnectionDegree,
)
from linkedin_mcp.tools.people.search.models.people_search_filter_base import PeopleSearchFilterBase
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters


class ConnectionsSearchFilters(PeopleSearchFilterBase):
    """People filters for established connections; first degree is server-enforced."""

    def as_people_search_filters(self) -> PeopleSearchFilters:
        return PeopleSearchFilters.model_validate(
            {
                **self.model_dump(mode="python"),
                "connection_degrees": (PeopleSearchConnectionDegree.FIRST,),
            }
        )
