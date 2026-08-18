from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
)
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode
from linkedin_mcp.tools.posts.create.models.video_caption_mode import VideoCaptionMode


class VideoPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.VIDEO] = PostCreateMode.VIDEO
    video_asset_ref: AssetReference
    thumbnail_asset_ref: AssetReference | None = None
    caption_mode: VideoCaptionMode = VideoCaptionMode.NONE
    caption_asset_ref: AssetReference | None = None
    review_auto_captions: bool = False

    @model_validator(mode="after")
    def validate_caption_options(self) -> VideoPostContent:
        if self.caption_mode is VideoCaptionMode.FILE and self.caption_asset_ref is None:
            raise ValueError("File captions require caption_asset_ref")
        if self.caption_mode is not VideoCaptionMode.FILE and self.caption_asset_ref is not None:
            raise ValueError("caption_asset_ref is valid only for file captions")
        if self.caption_mode is not VideoCaptionMode.AUTO and self.review_auto_captions:
            raise ValueError("review_auto_captions requires automatic captions")
        refs = tuple(
            value
            for value in (
                self.video_asset_ref,
                self.thumbnail_asset_ref,
                self.caption_asset_ref,
            )
            if value is not None
        )
        if len(set(refs)) != len(refs):
            raise ValueError("Video, thumbnail, and caption assets must be distinct")
        return self
