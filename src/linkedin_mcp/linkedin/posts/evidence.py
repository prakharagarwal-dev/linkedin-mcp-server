"""Evidence validation for LinkedIn posts and comments."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.common import SourceReference, SourceType
from linkedin_mcp.linkedin.posts.models import (
    CommentThread,
    PostCommentsCoverage,
    PostObservation,
    PostSearchCoverage,
    PostSummary,
)
from linkedin_mcp.linkedin.source import source_reference, verify_visible_items
from linkedin_mcp.linkedin.urls import (
    post_reference_from_comment_ref,
    post_reference_from_value,
)


def source_from_post_search(
    *,
    source_url: str,
    captured_text: str,
    posts: tuple[PostSummary, ...],
    coverage: PostSearchCoverage,
) -> SourceReference:
    if coverage.result_count != len(posts):
        raise ParserDriftError("Post-search coverage conflicts with the captured result count.")
    verify_visible_items(
        captured_text,
        ((post.post_ref, post.visible_text) for post in posts),
        item_kind="post",
    )
    return source_reference(
        source_type=SourceType.POST_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
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


def source_from_post_comments(
    *,
    source_url: str,
    captured_text: str,
    threads: tuple[CommentThread, ...],
    coverage: PostCommentsCoverage,
) -> SourceReference:
    comments = tuple(comment for thread in threads for comment in (thread.comment, *thread.replies))
    if post_reference_from_value(source_url) != coverage.post_ref:
        raise ParserDriftError("The comment source URL conflicts with the requested post.")
    for thread in threads:
        if thread.comment.parent_comment_ref is not None:
            raise ParserDriftError("A top-level LinkedIn comment has an unexpected parent.")
        for reply in thread.replies:
            if reply.parent_comment_ref != thread.comment.comment_ref:
                raise ParserDriftError("A LinkedIn reply is attached to a conflicting parent.")
    for comment in comments:
        if (
            comment.post_ref != coverage.discussion_post_ref
            or post_reference_from_comment_ref(comment.comment_ref) != comment.post_ref
        ):
            raise ParserDriftError("A captured comment belongs to a different LinkedIn post.")
        text_missing = comment.text is not None and comment.text not in comment.visible_text
        attachment_missing = any(
            attachment.visible_text not in comment.visible_text
            for attachment in comment.attachments
        )
        if text_missing or attachment_missing or comment.visible_text not in captured_text:
            raise ParserDriftError(
                f"Comment {comment.comment_ref!r} lacks exact visible content evidence."
            )
    return source_reference(
        source_type=SourceType.POST_COMMENTS,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
