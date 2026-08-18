from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    PostReference,
    StrictModel,
)


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
