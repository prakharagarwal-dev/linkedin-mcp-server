from __future__ import annotations

from enum import StrEnum


class PostContentType(StrEnum):
    TEXT = "text"
    LINK = "link"
    ARTICLE = "article"
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    LIVE_VIDEO = "live_video"
    NEWSLETTER = "newsletter"
    EVENT = "event"
    JOB = "job"
    POLL = "poll"
    REPOST = "repost"
    CELEBRATION = "celebration"
    OTHER = "other"
