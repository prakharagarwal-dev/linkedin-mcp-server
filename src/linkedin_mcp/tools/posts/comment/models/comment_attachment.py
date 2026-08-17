from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools.posts.comment.models.comment_gif_attachment import CommentGifAttachment
from linkedin_mcp.tools.posts.comment.models.comment_photo_attachment import CommentPhotoAttachment

CommentAttachment = Annotated[
    CommentPhotoAttachment | CommentGifAttachment,
    Field(discriminator="attachment_type"),
]
