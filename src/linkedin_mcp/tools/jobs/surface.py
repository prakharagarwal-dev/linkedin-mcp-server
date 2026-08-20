"""Visible job UI parsing shared by search and detail pages."""

from __future__ import annotations

import re

from linkedin_mcp.tools.jobs.models.job_workplace_type import JobWorkplaceType
from linkedin_mcp.ui import LinkedInLocator as Locator

LISTED_PATTERN = re.compile(
    r"\b(?:reposted\s+)?(?:\d+\s+)?(?:minute|hour|day|week|month)s?\s+ago\b|\breposted\b",
    re.IGNORECASE,
)

WORKPLACE_VALUES = {
    "remote": JobWorkplaceType.REMOTE,
    "hybrid": JobWorkplaceType.HYBRID,
    "on-site": JobWorkplaceType.ON_SITE,
}

WORKPLACE_LABELS = {value: label for label, value in WORKPLACE_VALUES.items()}


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def first_text(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = (await locator.first.inner_text()).strip()
    return value or None


async def first_href(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = await locator.first.get_attribute("href")
    return value.strip() if value and value.strip() else None


def first_pattern_text(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0).strip()
    return None
