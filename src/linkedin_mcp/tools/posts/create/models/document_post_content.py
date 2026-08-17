from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    AssetReference,
)
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class DocumentPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.DOCUMENT] = PostCreateMode.DOCUMENT
    document_asset_ref: AssetReference
    document_title: Annotated[str, Field(min_length=1, max_length=400)]
