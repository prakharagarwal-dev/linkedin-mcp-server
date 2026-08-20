from __future__ import annotations

import time
from typing import cast

import pytest
from playwright.async_api import Locator

from linkedin_mcp.infra.playwright import Paced


class _Control:
    def __init__(self) -> None:
        self.clicks = 0

    async def click(self) -> None:
        self.clicks += 1


@pytest.mark.asyncio
async def test_paced_waits_before_each_playwright_action() -> None:
    paced = Paced(delay_seconds=0.02)
    control = _Control()
    started_at = time.monotonic()

    await paced.click(cast(Locator, control))
    first_elapsed = time.monotonic() - started_at
    await paced.click(cast(Locator, control))
    second_elapsed = time.monotonic() - started_at

    assert first_elapsed >= 0.015
    assert second_elapsed >= 0.035
    assert control.clicks == 2


@pytest.mark.asyncio
async def test_paced_can_be_disabled_for_offline_execution() -> None:
    paced = Paced(delay_seconds=0)
    control = _Control()

    await paced.click(cast(Locator, control))

    assert control.clicks == 1


def test_paced_rejects_a_negative_delay() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        Paced(delay_seconds=-0.1)
