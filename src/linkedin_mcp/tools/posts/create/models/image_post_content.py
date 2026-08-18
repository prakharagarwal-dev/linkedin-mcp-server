from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode
from linkedin_mcp.tools.posts.create.models.post_image_input import PostImageInput


class ImagePostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.IMAGES] = PostCreateMode.IMAGES
    images: Annotated[tuple[PostImageInput, ...], Field(min_length=1, max_length=20)]
