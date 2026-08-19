"""Visible company UI parsing shared by search and profile pages."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.infra.playwright import Paced

VISIBLE_COUNT = r"\d[\d,.]*[KMB]?\+?"

FOLLOWER_COUNT_PATTERN = re.compile(
    rf"\b{VISIBLE_COUNT}\s+followers?\b",
    re.IGNORECASE,
)

ASSOCIATED_MEMBER_PATTERN = re.compile(
    rf"\b{VISIBLE_COUNT}\s+(?:associated\s+)?(?:members?|employees?)\b",
    re.IGNORECASE,
)

ACTION_LINES = frozenset(
    {
        "follow",
        "following",
        "message",
        "visit website",
        "more",
        "see all",
        "show all",
    }
)

INITIAL_RESULTS_POLL_ATTEMPTS = 20

INITIAL_RESULTS_POLL_DELAY_MS = 250


def unique_lines(value: str) -> list[str]:
    values: list[str] = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if line and line not in values:
            values.append(line)
    return values


async def first_visible_text(locator: Locator) -> str | None:
    for index in range(min(await locator.count(), 100)):
        candidate = locator.nth(index)
        if not await candidate.is_visible():
            continue
        value = (await candidate.inner_text()).strip()
        if value:
            return value
    return None


async def expand_and_scroll(paced: Paced, page: Page) -> None:
    main = page.locator("main")
    try:
        await main.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError("LinkedIn Company surface has no visible main region.") from error
    source_path = urlsplit(page.url).path.rstrip("/")
    for _ in range(8):
        await paced.evaluate(main, "element => { element.scrollTop = element.scrollHeight; }")
        await paced.keyboard_press(page.keyboard, "End")
        await page.wait_for_timeout(200)
        if urlsplit(page.url).path.rstrip("/") != source_path:
            raise ParserDriftError("LinkedIn Company surface navigated away while scrolling.")
    buttons = main.get_by_role(
        "button",
        name=re.compile(r"^(?:see more|show more)", re.IGNORECASE),
    )
    for index in range(min(await buttons.count(), 100)):
        button = buttons.nth(index)
        try:
            if await button.is_visible():
                source_url = page.url
                await paced.click(button, timeout=1_000)
                if page.url != source_url:
                    raise ParserDriftError(
                        "A Company content-expansion control unexpectedly navigated away."
                    )
        except PlaywrightTimeoutError:
            continue
    await paced.evaluate(main, "element => { element.scrollTop = 0; }")
    await paced.keyboard_press(page.keyboard, "Home")
