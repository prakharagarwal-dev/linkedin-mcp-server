"""Models for `linkedin_mcp.tools.connections.list`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import StopReason, StrictModel
from linkedin_mcp.tools.connections.list.models.connections_sort_by import ConnectionsSortBy


class ConnectionsListCoverage(StrictModel):
    sort_by: ConnectionsSortBy
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime
