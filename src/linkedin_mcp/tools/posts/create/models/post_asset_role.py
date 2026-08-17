from __future__ import annotations

from enum import StrEnum


class PostAssetRole(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    VIDEO_THUMBNAIL = "video_thumbnail"
    VIDEO_CAPTIONS = "video_captions"
    DOCUMENT = "document"
    CELEBRATION_IMAGE = "celebration_image"
    EVENT_COVER_IMAGE = "event_cover_image"
    COMMENT_IMAGE = "comment_image"
    MESSAGE_ATTACHMENT = "message_attachment"
