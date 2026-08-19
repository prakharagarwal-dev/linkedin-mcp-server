"""Models owned by `linkedin.posts.get`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


PostReference = Annotated[
    str, StringConstraints(pattern="^(?:activity|share|ugc-post):[0-9]{5,30}$")
]


class SourceType(StrEnum):
    POST = "linkedin_post"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class PostContentType(StrEnum):
    TEXT = "text"
    LINK = "link"
    ARTICLE = "article"
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    LIVE_VIDEO = "live_video"
    NEWSLETTER = "newsletter"
    EVENT = "event"
    JOB = "job"
    POLL = "poll"
    REPOST = "repost"
    CELEBRATION = "celebration"
    OTHER = "other"


class ReactionState(StrEnum):
    NONE = "none"
    LIKE = "like"
    CELEBRATE = "celebrate"
    SUPPORT = "support"
    LOVE = "love"
    INSIGHTFUL = "insightful"
    FUNNY = "funny"


class PostAttachment(StrictModel):
    content_type: PostContentType
    label: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    url: HttpUrl | None = None
    preview_url: HttpUrl | None = None
    page_count: Annotated[int, Field(ge=1, le=10_000)] | None = None
    duration_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> PostAttachment:
        if not any((self.label, self.url, self.preview_url, self.visible_text)):
            raise ValueError(
                "A post attachment requires visible identity or a visible resource URL"
            )
        if self.page_count is not None and self.content_type is not PostContentType.DOCUMENT:
            raise ValueError("Only a document attachment can expose page_count")
        return self


class PostAuthorType(StrEnum):
    MEMBER = "member"
    COMPANY = "company"
    UNKNOWN = "unknown"


PostProfileSlug = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{2,199}$",
    ),
]


PostCompanySlug = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"),
]


class PostAuthor(StrictModel):
    author_type: PostAuthorType
    name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: PostProfileSlug | None = None
    company_slug: PostCompanySlug | None = None
    author_url: HttpUrl | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    relationship_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    verified: bool = False
    viewer_is_author: bool = False

    @model_validator(mode="after")
    def validate_typed_identity(self) -> PostAuthor:
        if self.author_type is PostAuthorType.MEMBER and not self.profile_slug:
            raise ValueError("A member post author requires profile_slug")
        if self.author_type is PostAuthorType.COMPANY and not self.company_slug:
            raise ValueError("A company post author requires company_slug")
        return self


class PostDetailCoverage(StrictModel):
    requested_post_ref: PostReference
    displayed_post_ref: PostReference
    pages_visited: Annotated[int, Field(ge=1, le=2)]
    source_urls: Annotated[tuple[HttpUrl, ...], Field(min_length=1, max_length=2)]
    text_expanded: bool
    attachment_count: Annotated[int, Field(ge=0)]
    link_count: Annotated[int, Field(ge=0)]
    mention_count: Annotated[int, Field(ge=0)]
    hashtag_count: Annotated[int, Field(ge=0)]
    poll_present: bool
    reshared_post_present: bool
    truncated: Literal[False] = False
    captured_at: datetime

    @model_validator(mode="after")
    def validate_source_pages(self) -> PostDetailCoverage:
        if len(self.source_urls) != self.pages_visited:
            raise ValueError("Post detail source URLs conflict with pages_visited")
        if len({str(url) for url in self.source_urls}) != len(self.source_urls):
            raise ValueError("Post detail source URLs must be unique")
        return self


class PostEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    captured_at: datetime


class PostGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference


class PostLink(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=2_000)]
    url: HttpUrl


class PostPollOption(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    percentage_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    vote_count_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    selected: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostPollState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class PostPoll(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    options: Annotated[tuple[PostPollOption, ...], Field(min_length=2, max_length=5)]
    total_votes_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    state: PostPollState = PostPollState.UNKNOWN
    state_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    viewer_has_voted: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_options(self) -> PostPoll:
        normalized = tuple(option.text.casefold() for option in self.options)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Visible poll options must be unique")
        return self


class PostResharedContent(StrictModel):
    post_ref: PostReference | None = None
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    content_type: PostContentType = PostContentType.TEXT
    attachments: tuple[PostAttachment, ...] = ()
    links: tuple[PostLink, ...] = ()
    hashtags: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = ()
    mentions: tuple[PostLink, ...] = ()
    poll: PostPoll | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostObservation(StrictModel):
    post_ref: PostReference
    displayed_post_ref: PostReference
    post_url: HttpUrl
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    visibility_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    promoted: bool = False
    content_type: PostContentType = PostContentType.TEXT
    attachments: tuple[PostAttachment, ...] = ()
    links: tuple[PostLink, ...] = ()
    hashtags: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = ()
    mentions: tuple[PostLink, ...] = ()
    poll: PostPoll | None = None
    reshared_post: PostResharedContent | None = None
    viewer_reaction: ReactionState | None = None
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comment_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    repost_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    impression_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comments_enabled: bool = False
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[PostEvidence, ...]
    coverage: PostDetailCoverage
    captured_at: datetime

    @model_validator(mode="after")
    def validate_detail_consistency(self) -> PostObservation:
        if self.coverage.requested_post_ref != self.post_ref:
            raise ValueError("Post detail coverage conflicts with the requested post reference")
        if self.coverage.displayed_post_ref != self.displayed_post_ref:
            raise ValueError("Post detail coverage conflicts with the displayed post reference")
        if self.coverage.attachment_count != len(self.attachments):
            raise ValueError("Post detail coverage conflicts with the attachment count")
        if self.coverage.link_count != len(self.links):
            raise ValueError("Post detail coverage conflicts with the link count")
        if self.coverage.mention_count != len(self.mentions):
            raise ValueError("Post detail coverage conflicts with the mention count")
        if self.coverage.hashtag_count != len(self.hashtags):
            raise ValueError("Post detail coverage conflicts with the hashtag count")
        if self.coverage.poll_present != (self.poll is not None):
            raise ValueError("Post detail coverage conflicts with the poll state")
        if self.coverage.reshared_post_present != (self.reshared_post is not None):
            raise ValueError("Post detail coverage conflicts with the reshared-post state")
        if self.coverage.captured_at != self.captured_at:
            raise ValueError("Post detail coverage conflicts with the capture time")
        if str(self.coverage.source_urls[0]) != str(self.post_url):
            raise ValueError("Post detail coverage conflicts with the requested source URL")
        if (self.content_type is PostContentType.POLL) != (self.poll is not None):
            raise ValueError("Post poll type and visible poll details must agree")
        if (self.content_type is PostContentType.REPOST) != (self.reshared_post is not None):
            raise ValueError("Post repost type and visible reshared-post details must agree")
        if (self.coverage.pages_visited == 2) != (self.reshared_post is not None):
            raise ValueError("A repost must capture exactly the wrapper and original pages")
        source_urls = {str(url) for url in self.coverage.source_urls}
        for evidence in self.evidence:
            if (
                str(evidence.source_url) not in source_urls
                or evidence.captured_at != self.captured_at
            ):
                raise ValueError("Post evidence conflicts with the detail capture")
        return self


class PostGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    post: PostObservation
    sources: tuple[SourceReference, ...]
