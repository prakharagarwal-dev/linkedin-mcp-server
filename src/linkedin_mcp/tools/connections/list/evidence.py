"""Evidence validation for `linkedin.connections.list`."""

from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference, verify_visible_items
from linkedin_mcp.tools.connections.list.models.connection_summary import ConnectionSummary
from linkedin_mcp.tools.connections.list.models.connections_list_coverage import (
    ConnectionsListCoverage,
)


def source_from_connections(
    *,
    source_url: str,
    captured_text: str,
    connections: tuple[ConnectionSummary, ...],
    coverage: ConnectionsListCoverage,
) -> SourceReference:
    verify_visible_items(
        captured_text,
        ((connection.profile_slug, connection.visible_text) for connection in connections),
        item_kind="connection",
    )
    return source_reference(
        source_type=SourceType.CONNECTIONS,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
