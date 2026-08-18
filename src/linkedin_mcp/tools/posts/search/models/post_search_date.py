from __future__ import annotations

from enum import StrEnum


class PostSearchDate(StrEnum):
    ANY_TIME = "any_time"
    PAST_24_HOURS = "past_24_hours"
    PAST_WEEK = "past_week"
    PAST_MONTH = "past_month"
