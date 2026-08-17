from __future__ import annotations

from enum import StrEnum


class PostCreateMode(StrEnum):
    TEXT = "text"
    IMAGES = "images"
    VIDEO = "video"
    DOCUMENT = "document"
    POLL = "poll"
    CELEBRATION = "celebration"
    EVENT = "event"
    HIRING = "hiring"
    EXPERT_REQUEST = "expert_request"
