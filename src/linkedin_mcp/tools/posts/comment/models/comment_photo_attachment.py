from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    AssetReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_type import (
    CommentAttachmentType,
)


class CommentPhotoAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.PHOTO] = CommentAttachmentType.PHOTO
    asset_ref: AssetReference
