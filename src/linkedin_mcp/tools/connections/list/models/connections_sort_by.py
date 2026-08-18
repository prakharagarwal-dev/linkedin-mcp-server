"""Models for `linkedin_mcp.tools.connections.list`."""

from __future__ import annotations

from enum import StrEnum


class ConnectionsSortBy(StrEnum):
    RECENTLY_ADDED = "recently_added"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
