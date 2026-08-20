"""Evidence validation for `linkedin.posts.get`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.browser.urls import post_reference_from_value
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.posts.get.models import PostObservation, SourceReference, SourceType


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


def source_from_post(observation: PostObservation) -> SourceReference:
    source_urls = {str(url) for url in observation.coverage.source_urls}
    if (
        str(observation.post_url) != str(observation.coverage.source_urls[0])
        or post_reference_from_value(str(observation.post_url)) != observation.post_ref
    ):
        raise ParserDriftError("Post detail coverage conflicts with its requested source URL.")
    for evidence in observation.evidence:
        if (
            str(evidence.source_url) not in source_urls
            or evidence.quote not in observation.visible_text
            or evidence.captured_at != observation.captured_at
        ):
            raise ParserDriftError(
                f"Post evidence for field {evidence.field!r} is not an exact visible substring."
            )
    return source_reference(
        source_type=SourceType.POST,
        source_url=str(observation.post_url),
        captured_at=observation.captured_at,
        captured_text=observation.visible_text,
    )
