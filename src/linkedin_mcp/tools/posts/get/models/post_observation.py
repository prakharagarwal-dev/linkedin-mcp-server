from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.get.models.post_attachment import PostAttachment
from linkedin_mcp.tools.posts.get.models.post_detail_coverage import PostDetailCoverage
from linkedin_mcp.tools.posts.get.models.post_evidence import PostEvidence
from linkedin_mcp.tools.posts.get.models.post_link import PostLink
from linkedin_mcp.tools.posts.get.models.post_poll import PostPoll
from linkedin_mcp.tools.posts.get.models.post_reshared_content import PostResharedContent
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.react.models.reaction_state import ReactionState
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType


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
