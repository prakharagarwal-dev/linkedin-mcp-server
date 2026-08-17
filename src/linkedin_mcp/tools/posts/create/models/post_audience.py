from __future__ import annotations

from enum import StrEnum


class PostAudience(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    GROUP = "group"
