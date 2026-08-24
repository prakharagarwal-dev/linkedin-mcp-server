"""LinkedIn Messaging URL parsing and construction."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from linkedin_mcp.errors import InvalidTargetError

_CONVERSATION_ID_PATTERN = r"[A-Za-z0-9_%=-]{3,500}"
_CONVERSATION_PATH = re.compile(
    rf"^/messaging/thread/(?P<conversation_id>{_CONVERSATION_ID_PATTERN})(?:/|$)"
)


def conversation_id_from_url(url: str) -> str | None:
    match = _CONVERSATION_PATH.match(urlsplit(url).path)
    return match.group("conversation_id") if match else None


def canonical_conversation_url(conversation_id: str) -> str:
    if not re.fullmatch(_CONVERSATION_ID_PATTERN, conversation_id):
        raise InvalidTargetError(
            "LinkedIn conversation IDs must be one safe visible messaging path segment."
        )
    return f"https://www.linkedin.com/messaging/thread/{conversation_id}/"
