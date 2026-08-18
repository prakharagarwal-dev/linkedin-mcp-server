from __future__ import annotations

from enum import StrEnum


class PostPollState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"
