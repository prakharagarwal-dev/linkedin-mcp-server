from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    JobId,
)
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class HiringPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.HIRING] = PostCreateMode.HIRING
    company_name: Annotated[str, Field(min_length=1, max_length=500)]
    job_id: JobId
    job_title: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def require_text(self) -> HiringPostContent:
        if self.text is None:
            raise ValueError("A hiring post requires text")
        return self
