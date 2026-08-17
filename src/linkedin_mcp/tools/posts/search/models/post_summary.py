from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType


class PostSummary(StrictModel):
    post_ref: PostReference
    post_url: HttpUrl
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    content_type: PostContentType = PostContentType.TEXT
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comment_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    repost_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
