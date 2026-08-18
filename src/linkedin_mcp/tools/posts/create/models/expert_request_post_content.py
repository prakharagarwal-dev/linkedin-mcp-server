from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from linkedin_mcp.tools.posts.create.models.expert_request_category import ExpertRequestCategory
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class ExpertRequestPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.EXPERT_REQUEST] = PostCreateMode.EXPERT_REQUEST
    category: ExpertRequestCategory
    location_label: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_description(self) -> ExpertRequestPostContent:
        if self.text is None or not 25 <= len(self.text) <= 750:
            raise ValueError("An expert-request description must be 25 to 750 characters")
        return self
