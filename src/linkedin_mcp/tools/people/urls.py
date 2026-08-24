"""LinkedIn profile URL parsing and construction."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from linkedin_mcp.errors import InvalidTargetError

_PROFILE_SLUG_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{2,199}"
_PROFILE_SLUG_PATTERN = rf"^{_PROFILE_SLUG_SEGMENT_PATTERN}$"
_PROFILE_PATH = re.compile(rf"^/in/(?P<profile_slug>{_PROFILE_SLUG_SEGMENT_PATTERN})(?:/|$)")


def profile_slug_from_url(url: str) -> str | None:
    match = _PROFILE_PATH.match(urlsplit(url).path)
    return match.group("profile_slug") if match else None


def canonical_profile_url(profile_slug: str) -> str:
    if not re.fullmatch(_PROFILE_SLUG_PATTERN, profile_slug):
        raise InvalidTargetError(
            "LinkedIn profile slugs must contain 3 to 200 letters, digits, or hyphens."
        )
    return f"https://www.linkedin.com/in/{profile_slug}/"
