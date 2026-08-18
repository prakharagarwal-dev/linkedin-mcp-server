from __future__ import annotations

from enum import StrEnum


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    SYSTEM = "system"
