from __future__ import annotations

import time

import pytest

from linkedin_mcp.tools._shared.pacing import NavigationPacer


@pytest.mark.asyncio
async def test_navigation_pacer_waits_between_local_browser_navigations() -> None:
    pacer = NavigationPacer(account_id="personal", interval_seconds=0.02)
    started_at = time.monotonic()

    await pacer.wait()
    first_elapsed = time.monotonic() - started_at
    await pacer.wait()
    second_elapsed = time.monotonic() - started_at
    pacer.close()

    assert first_elapsed >= 0.015
    assert second_elapsed >= 0.035


@pytest.mark.asyncio
async def test_navigation_pacer_can_be_disabled_for_offline_execution() -> None:
    pacer = NavigationPacer(account_id="personal", interval_seconds=0)

    await pacer.wait()
    pacer.close()
    pacer.close()
