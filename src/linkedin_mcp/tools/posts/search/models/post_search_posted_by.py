from __future__ import annotations

from enum import StrEnum


class PostSearchPostedBy(StrEnum):
    ME = "me"
    FIRST_CONNECTIONS = "first_connections"
    PEOPLE_YOU_FOLLOW = "people_you_follow"
