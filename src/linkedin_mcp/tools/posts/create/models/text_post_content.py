from __future__ import annotations

from typing import Literal

from pydantic import HttpUrl, model_validator

from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class TextPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.TEXT] = PostCreateMode.TEXT
    link_url: HttpUrl | None = None
    show_link_preview: bool = True

    @model_validator(mode="after")
    def validate_link(self) -> TextPostContent:
        if self.text is None:
            raise ValueError("A text post requires text")
        if self.link_url is None and not self.show_link_preview:
            raise ValueError("A link preview can be removed only when link_url is supplied")
        if self.link_url is not None and str(self.link_url) not in self.text:
            raise ValueError("link_url must occur exactly in the post text")
        return self
