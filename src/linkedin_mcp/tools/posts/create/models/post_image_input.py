from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.create.models.post_image_edit_input import PostImageEditInput
from linkedin_mcp.tools.posts.create.models.post_image_tag_input import PostImageTagInput


class PostImageInput(StrictModel):
    asset_ref: AssetReference
    alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    tags: Annotated[
        tuple[PostImageTagInput, ...],
        Field(max_length=30),
    ] = ()
    edit: PostImageEditInput | None = None

    @model_validator(mode="after")
    def reject_duplicate_tags(self) -> PostImageInput:
        identities = tuple(
            (
                "member",
                member.profile_slug,
            )
            if member.profile_slug is not None
            else ("company", member.company_slug)
            for member in self.tags
        )
        if len(set(identities)) != len(identities):
            raise ValueError("Image tags must be unique")
        return self
