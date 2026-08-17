from __future__ import annotations

from enum import StrEnum


class ConversationFilter(StrEnum):
    JOBS = "jobs"
    UNREAD = "unread"
    CONNECTIONS = "connections"
    STARRED = "starred"
    INMAIL = "inmail"
