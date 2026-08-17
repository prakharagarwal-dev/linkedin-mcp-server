"""Evidence validation for `linkedin.invitations.list`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.invitations.list.models import InvitationListCoverage, InvitationSummary


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
