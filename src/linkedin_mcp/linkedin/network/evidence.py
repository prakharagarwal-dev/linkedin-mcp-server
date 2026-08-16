"""Evidence validation for LinkedIn connections and invitations."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.common import SourceReference, SourceType
from linkedin_mcp.linkedin.network.models import (
    ConnectionsListCoverage,
    ConnectionSummary,
    InvitationListCoverage,
    InvitationSummary,
)
from linkedin_mcp.linkedin.source import source_reference, verify_visible_items


def source_from_invitation_list(
    *,
    source_url: str,
    captured_text: str,
    invitations: tuple[InvitationSummary, ...],
    coverage: InvitationListCoverage,
) -> SourceReference:
    if coverage.result_count != len(invitations):
        raise ParserDriftError("Invitation coverage conflicts with the returned live page.")
    allowed_evidence_urls = {str(url).rstrip("/") for url in coverage.view_source_urls.values()}
    for invitation in invitations:
        if (
            invitation.direction is not coverage.direction
            or invitation.visible_text not in captured_text
        ):
            raise ParserDriftError(
                "A returned invitation conflicts with its selected view or visible evidence."
            )
        for evidence in invitation.evidence:
            if (
                str(evidence.source_url).rstrip("/") not in allowed_evidence_urls
                or evidence.captured_at != coverage.captured_at
                or evidence.quote not in invitation.visible_text
            ):
                raise ParserDriftError(
                    f"Invitation {invitation.invitation_ref!r} has invalid field evidence."
                )
    return source_reference(
        source_type=SourceType.INVITATIONS,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
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
