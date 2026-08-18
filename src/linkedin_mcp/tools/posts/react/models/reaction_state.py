from __future__ import annotations

from enum import StrEnum


class ReactionState(StrEnum):
    NONE = "none"
    LIKE = "like"
    CELEBRATE = "celebrate"
    SUPPORT = "support"
    LOVE = "love"
    INSIGHTFUL = "insightful"
    FUNNY = "funny"
