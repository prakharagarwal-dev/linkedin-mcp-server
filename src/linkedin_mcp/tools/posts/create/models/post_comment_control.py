from __future__ import annotations

from enum import StrEnum


class PostCommentControl(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    NO_ONE = "no_one"
