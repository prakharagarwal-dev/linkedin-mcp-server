"""Visible person UI parsing shared by search and profile pages."""

from __future__ import annotations

import re

from playwright.async_api import Locator

from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree

CONNECTION_DEGREE_PATTERN = re.compile(r"\b(1st|2nd|3rd)\b", re.IGNORECASE)

CONNECTION_COUNT_PATTERN = re.compile(
    r"\b(?:[\d,.+]+|500\+)\s+connections?\b",
    re.IGNORECASE,
)

FOLLOWER_COUNT_PATTERN = re.compile(r"\b[\d,.+]+\s+followers?\b", re.IGNORECASE)

ACTION_LINES = frozenset(
    {
        "connect",
        "follow",
        "message",
        "more",
        "pending",
        "view profile",
        "contact info",
        "show all",
        "see more",
    }
)


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def unique_lines(text: str) -> list[str]:
    values: list[str] = []
    for line in lines(text):
        if values and values[-1] == line:
            continue
        values.append(line)
    return values


async def first_text(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = (await locator.first.inner_text()).strip()
    return value or None


def connection_degree(text: str) -> PersonConnectionDegree | None:
    match = CONNECTION_DEGREE_PATTERN.search(text)
    if match is None:
        if "out of network" in text.casefold():
            return PersonConnectionDegree.OUT_OF_NETWORK
        return None
    return {
        "1st": PersonConnectionDegree.FIRST,
        "2nd": PersonConnectionDegree.SECOND,
        "3rd": PersonConnectionDegree.THIRD_OR_MORE,
    }[match.group(1).casefold()]
