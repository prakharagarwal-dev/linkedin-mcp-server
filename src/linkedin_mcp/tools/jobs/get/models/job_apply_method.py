from __future__ import annotations

from enum import StrEnum


class JobApplyMethod(StrEnum):
    EASY_APPLY = "easy_apply"
    EXTERNAL = "external"
    UNAVAILABLE = "unavailable"
