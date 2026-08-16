"""Detection for authentication loss, restrictions, and unexpected navigation."""

from __future__ import annotations

from urllib.parse import urlsplit

from playwright.async_api import Page

from linkedin_mcp.errors import AuthenticationRequiredError, RestrictionDetectedError
from linkedin_mcp.linkedin.urls import validate_linkedin_url

_RESTRICTION_PATHS = ("/checkpoint/", "/authwall")
_LOGIN_PATHS = ("/login", "/uas/login")
_RESTRICTION_PHRASES = (
    "unusual activity",
    "temporarily restricted",
    "security verification",
    "verify your identity",
    "too many requests",
)


async def assert_safe_linkedin_page(page: Page, allowed_hosts: tuple[str, ...]) -> None:
    validated = validate_linkedin_url(page.url, allowed_hosts)
    path = urlsplit(validated).path.lower()
    if any(marker in path for marker in _RESTRICTION_PATHS):
        raise RestrictionDetectedError(
            "LinkedIn presented a security checkpoint or access restriction."
        )
    if any(path.startswith(marker) for marker in _LOGIN_PATHS):
        raise AuthenticationRequiredError("The LinkedIn browser session has expired.")

    body = page.locator("body")
    try:
        text = (await body.inner_text(timeout=2_000)).strip()
    except Exception:
        return
    normalized = " ".join(text.lower().split())
    if len(normalized) < 2_000 and any(phrase in normalized for phrase in _RESTRICTION_PHRASES):
        raise RestrictionDetectedError("LinkedIn returned a restriction-shaped page.")
