from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.get.models.post_attachment import PostAttachment
from linkedin_mcp.tools.posts.get.models.post_link import PostLink
from linkedin_mcp.tools.posts.get.models.post_poll import PostPoll
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType


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
