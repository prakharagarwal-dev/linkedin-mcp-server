from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType


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
