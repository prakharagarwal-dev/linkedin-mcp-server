from __future__ import annotations

from enum import StrEnum


class PollDuration(StrEnum):
    ONE_DAY = "one_day"
    THREE_DAYS = "three_days"
    ONE_WEEK = "one_week"
    TWO_WEEKS = "two_weeks"
