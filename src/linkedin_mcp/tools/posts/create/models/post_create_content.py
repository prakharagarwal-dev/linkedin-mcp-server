from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools.posts.create.models.celebration_post_content import CelebrationPostContent
from linkedin_mcp.tools.posts.create.models.document_post_content import DocumentPostContent
from linkedin_mcp.tools.posts.create.models.event_post_content import EventPostContent
from linkedin_mcp.tools.posts.create.models.expert_request_post_content import (
    ExpertRequestPostContent,
)
from linkedin_mcp.tools.posts.create.models.hiring_post_content import HiringPostContent
from linkedin_mcp.tools.posts.create.models.image_post_content import ImagePostContent
from linkedin_mcp.tools.posts.create.models.poll_post_content import PollPostContent
from linkedin_mcp.tools.posts.create.models.text_post_content import TextPostContent
from linkedin_mcp.tools.posts.create.models.video_post_content import VideoPostContent

PostCreateContent = Annotated[
    TextPostContent
    | ImagePostContent
    | VideoPostContent
    | DocumentPostContent
    | PollPostContent
    | CelebrationPostContent
    | EventPostContent
    | HiringPostContent
    | ExpertRequestPostContent,
    Field(
        discriminator="mode",
        description=(
            "Typed post content discriminated by the required mode field; use mode, not kind."
        ),
    ),
]
