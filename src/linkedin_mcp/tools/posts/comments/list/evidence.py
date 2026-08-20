"""Evidence validation for `linkedin.posts.comments.list`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.posts.comments.list.models import (
    CommentThread,
    PostCommentsCoverage,
    SourceReference,
    SourceType,
)
from linkedin_mcp.ui.urls import (
    post_reference_from_comment_ref,
    post_reference_from_value,
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
