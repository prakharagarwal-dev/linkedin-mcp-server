"""LinkedIn Companies URL parsing and construction."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from linkedin_mcp.errors import InvalidTargetError

_COMPANY_SLUG_PATTERN = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?"
_COMPANY_PATH = re.compile(rf"^/company/(?P<company_slug>{_COMPANY_SLUG_PATTERN})(?:/|$)")


def company_slug_from_url(url: str) -> str | None:
    match = _COMPANY_PATH.match(urlsplit(url).path)
    return match.group("company_slug") if match else None


def canonical_company_url(company_slug: str, section: str | None = None) -> str:
    if not re.fullmatch(_COMPANY_SLUG_PATTERN, company_slug):
        raise InvalidTargetError(
            "LinkedIn company slugs must contain 1 to 200 letters, digits, or hyphens."
        )
    suffix = ""
    if section is not None:
        if section != "about":
            raise InvalidTargetError("The requested LinkedIn company section is unsupported.")
        suffix = f"{section}/"
    return f"https://www.linkedin.com/company/{company_slug}/{suffix}"
