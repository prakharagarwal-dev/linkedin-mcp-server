from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
)
from linkedin_mcp.tools.posts.create.models.celebration_type import CelebrationType
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class CelebrationPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.CELEBRATION] = PostCreateMode.CELEBRATION
    celebration_type: CelebrationType
    template_index: Annotated[int, Field(ge=1, le=22)] | None = 1
    image_asset_ref: AssetReference | None = None
    image_alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None

    @model_validator(mode="after")
    def validate_visual(self) -> CelebrationPostContent:
        if self.text is None:
            raise ValueError("A celebration post requires text")
        if (self.template_index is None) == (self.image_asset_ref is None):
            raise ValueError("A celebration requires exactly one LinkedIn template or custom image")
        if self.image_alt_text is not None and self.image_asset_ref is None:
            raise ValueError("Celebration alt text requires a custom image")
        return self
