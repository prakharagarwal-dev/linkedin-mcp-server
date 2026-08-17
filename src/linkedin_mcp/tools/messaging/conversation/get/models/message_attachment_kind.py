from __future__ import annotations

from enum import StrEnum


class MessageAttachmentKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"
