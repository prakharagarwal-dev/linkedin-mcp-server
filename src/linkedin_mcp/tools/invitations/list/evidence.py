"""Evidence validation for `linkedin.invitations.list`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.invitations.list.models import (
    InvitationListCoverage,
    InvitationSummary,
    SourceReference,
    SourceType,
)


def stable_source_id(
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    *,
    identity: str | None = None,
) -> str:
    fields = [source_type.value, source_url, captured_at.isoformat(), captured_text]
    if identity is not None:
        fields.append(identity)
    payload = "\x1f".join(fields).encode()
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"{source_type.value}:{digest}"


def source_reference(
    *,
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    identity: str | None = None,
) -> SourceReference:
    return SourceReference(
        source_id=stable_source_id(
            source_type,
            source_url,
            captured_at,
            captured_text,
            identity=identity,
        ),
        source_type=source_type,
        source_url=HttpUrl(source_url),
        captured_at=captured_at,
    )


def verify_visible_items(
    captured_text: str,
    items: Iterable[tuple[str, str]],
    *,
    item_kind: str,
) -> None:
    for reference, visible_text in items:
        if visible_text not in captured_text:
            raise ParserDriftError(
                f"Captured {item_kind} {reference!r} is not an exact source substring."
            )


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
