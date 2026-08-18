"""Evidence validation for `linkedin.posts.get`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools._shared.urls import post_reference_from_value
from linkedin_mcp.tools.posts.get.models.post_observation import PostObservation


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
