from __future__ import annotations

from enum import StrEnum


class PostAuthorType(StrEnum):
    MEMBER = "member"
    COMPANY = "company"
    UNKNOWN = "unknown"
