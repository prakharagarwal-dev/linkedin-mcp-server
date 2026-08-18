from __future__ import annotations

from enum import StrEnum


class ConversationCategory(StrEnum):
    FOCUSED = "focused"
    OTHER = "other"
    ARCHIVED = "archived"
    SPAM = "spam"
