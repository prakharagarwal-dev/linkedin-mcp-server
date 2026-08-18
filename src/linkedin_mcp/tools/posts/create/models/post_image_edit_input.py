from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.create.models.post_image_aspect_ratio import PostImageAspectRatio
from linkedin_mcp.tools.posts.create.models.post_image_filter import PostImageFilter


class PostImageEditInput(StrictModel):
    """Exact controls exposed by LinkedIn's current desktop image editor."""

    clockwise_quarter_turns: Annotated[int, Field(ge=-3, le=3)] = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    aspect_ratio: PostImageAspectRatio = PostImageAspectRatio.ORIGINAL
    zoom: Annotated[float, Field(ge=1.0, le=3.0, multiple_of=0.1)] = 1.0
    straighten_degrees: Annotated[int, Field(ge=-45, le=45)] = 0
    image_filter: PostImageFilter = PostImageFilter.ORIGINAL
    brightness: Annotated[int, Field(ge=-30, le=30)] = 0
    contrast: Annotated[int, Field(ge=-30, le=30)] = 0
    saturation: Annotated[int, Field(ge=-30, le=30)] = 0
    vignette: Annotated[int, Field(ge=-30, le=30)] = 0
