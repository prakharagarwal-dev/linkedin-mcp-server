"""Source metadata creation and exact-quote validation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.domain.models import (
    ActionPageResult,
    CommentThread,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
    CompanySearchCoverage,
    CompanySummary,
    ConnectionsListCoverage,
    ConnectionSummary,
    ConversationObservation,
    ConversationSearchCoverage,
    ConversationSummary,
    InvitationListCoverage,
    InvitationSummary,
    JobDetailObservation,
    JobSearchCoverage,
    JobSummary,
    PeopleSearchCoverage,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonSummary,
    PostCommentsCoverage,
    PostObservation,
    PostSearchCoverage,
    PostSummary,
    SourceReference,
    SourceType,
)
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.policy import (
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


def source_from_job_search(
    *,
    source_url: str,
    captured_text: str,
    jobs: tuple[JobSummary, ...],
    coverage: JobSearchCoverage,
) -> SourceReference:
    for job in jobs:
        for evidence in job.evidence:
            if evidence.quote not in job.visible_text or evidence.quote not in captured_text:
                raise ParserDriftError(
                    f"Evidence for job {job.job_id} field {evidence.field!r} "
                    "is not an exact captured visible-text substring."
                )
    return _source_reference(
        source_type=SourceType.JOB_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )


def source_from_job_detail(observation: JobDetailObservation) -> SourceReference:
    for evidence in observation.evidence:
        if evidence.quote not in observation.visible_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact visible-text substring."
            )
    return _source_reference(
        source_type=SourceType.JOB,
        source_url=str(observation.job_url),
        captured_at=observation.captured_at,
        captured_text=observation.visible_text,
    )


def source_from_people_search(
    *,
    source_url: str,
    captured_text: str,
    people: tuple[PersonSummary, ...],
    coverage: PeopleSearchCoverage,
) -> SourceReference:
    _verify_visible_items(
        captured_text,
        ((person.profile_slug, person.visible_text) for person in people),
        item_kind="person",
    )
    return _source_reference(
        source_type=SourceType.PEOPLE_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )


def source_from_company_search(
    *,
    source_url: str,
    captured_text: str,
    companies: tuple[CompanySummary, ...],
    coverage: CompanySearchCoverage,
) -> SourceReference:
    _verify_visible_items(
        captured_text,
        ((company.company_slug, company.visible_text) for company in companies),
        item_kind="company",
    )
    return _source_reference(
        source_type=SourceType.COMPANY_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
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
    _verify_visible_items(
        captured_text,
        ((post.post_ref, post.visible_text) for post in posts),
        item_kind="post",
    )
    return _source_reference(
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
    return _source_reference(
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
    return _source_reference(
        source_type=SourceType.POST_COMMENTS,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
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
    return _source_reference(
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
    _verify_visible_items(
        captured_text,
        ((connection.profile_slug, connection.visible_text) for connection in connections),
        item_kind="connection",
    )
    return _source_reference(
        source_type=SourceType.CONNECTIONS,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )


def source_from_conversation_search(
    *,
    source_url: str,
    captured_text: str,
    conversations: tuple[ConversationSummary, ...],
    coverage: ConversationSearchCoverage,
) -> SourceReference:
    _verify_visible_items(
        captured_text,
        (
            (conversation.conversation_ref, conversation.visible_text)
            for conversation in conversations
        ),
        item_kind="conversation",
    )
    return _source_reference(
        source_type=SourceType.MESSAGING_INBOX,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )


def source_from_conversation(observation: ConversationObservation) -> SourceReference:
    for message in observation.messages:
        text_missing = message.text is not None and message.text not in message.visible_text
        attachment_missing = any(
            attachment.visible_text not in message.visible_text
            for attachment in message.attachments
        )
        if (
            text_missing
            or attachment_missing
            or message.visible_text not in observation.visible_text
        ):
            raise ParserDriftError(
                f"Message {message.message_ref!r} is not an exact visible conversation substring."
            )
    return _source_reference(
        source_type=SourceType.MESSAGING_CONVERSATION,
        source_url=_conversation_source_url(observation),
        captured_at=observation.captured_at,
        captured_text=observation.visible_text,
    )


def source_from_action_execution(
    page_result: ActionPageResult,
    *,
    execution_id: str,
) -> SourceReference:
    return _source_reference(
        source_type=SourceType.ACTION_EXECUTION,
        source_url=str(page_result.source_url),
        captured_at=page_result.captured_at,
        captured_text=page_result.captured_text,
        identity=execution_id,
    )


def sources_from_person_profile(
    observation: PersonProfileObservation,
    captures: tuple[PersonProfilePageCapture, ...],
) -> tuple[SourceReference, ...]:
    if not captures:
        raise ParserDriftError("A member profile must retain at least one visible source.")
    captured_by_url = {str(capture.source_url): capture.captured_text for capture in captures}
    for evidence in observation.evidence:
        captured_text = captured_by_url.get(str(evidence.source_url))
        if captured_text is None or evidence.quote not in captured_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact source substring."
            )

    return tuple(
        _source_reference(
            source_type=SourceType.MEMBER_PROFILE,
            source_url=str(capture.source_url),
            captured_at=capture.captured_at,
            captured_text=capture.captured_text,
        )
        for capture in captures
    )


def sources_from_company_profile(
    observation: CompanyProfileObservation,
    captures: tuple[CompanyProfilePageCapture, ...],
) -> tuple[SourceReference, ...]:
    if tuple(capture.page_kind for capture in captures) != ("overview", "about"):
        raise ParserDriftError(
            "A company profile must retain exactly its overview and About sources."
        )
    captured_by_url = {str(capture.source_url): capture.captured_text for capture in captures}
    for evidence in observation.evidence:
        captured_text = captured_by_url.get(str(evidence.source_url))
        if captured_text is None or evidence.quote not in captured_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact company-source substring."
            )

    return tuple(
        _source_reference(
            source_type=SourceType.COMPANY_PROFILE,
            source_url=str(capture.source_url),
            captured_at=capture.captured_at,
            captured_text=capture.captured_text,
        )
        for capture in captures
    )


def _source_reference(
    *,
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    identity: str | None = None,
) -> SourceReference:
    source_id = stable_source_id(
        source_type,
        source_url,
        captured_at,
        captured_text,
        identity=identity,
    )
    return SourceReference(
        source_id=source_id,
        source_type=source_type,
        source_url=HttpUrl(source_url),
        captured_at=captured_at,
    )


def _verify_visible_items(
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


def _conversation_source_url(observation: ConversationObservation) -> str:
    if observation.conversation_id:
        return f"https://www.linkedin.com/messaging/thread/{observation.conversation_id}/"
    if observation.participant_profile_slug:
        return f"https://www.linkedin.com/in/{observation.participant_profile_slug}/"
    raise ParserDriftError("A conversation source requires a conversation or participant target.")
