from __future__ import annotations

from enum import StrEnum


class PeopleSearchConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"
