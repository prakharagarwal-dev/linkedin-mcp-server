from __future__ import annotations

import asyncio

import pytest

from linkedin_mcp.errors import AuthenticationRequiredError, RestrictionDetectedError
from linkedin_mcp.linkedin.authentication import AuthenticationCoordinator
from linkedin_mcp.linkedin.models import SessionAuthenticationState


@pytest.mark.asyncio
async def test_first_run_opens_login_then_validates_without_blocking_start() -> None:
    present = False
    login_started = asyncio.Event()
    finish_login = asyncio.Event()
    calls: list[str] = []

    async def reset() -> None:
        calls.append("reset")

    async def login() -> None:
        nonlocal present
        calls.append("login")
        login_started.set()
        await finish_login.wait()
        present = True

    async def validate() -> None:
        calls.append("validate")

    coordinator = AuthenticationCoordinator(
        automatic=True,
        state_present=lambda: present,
        reset_session=reset,
        login=login,
        validate=validate,
    )

    coordinator.start()
    await asyncio.wait_for(login_started.wait(), timeout=1)
    assert coordinator.state is SessionAuthenticationState.LOGIN_IN_PROGRESS
    assert coordinator.login_browser_open is True

    finish_login.set()
    await coordinator.ensure_ready()

    assert coordinator.state is SessionAuthenticationState.AUTHENTICATED
    assert calls == ["reset", "login", "validate"]
    await coordinator.close()


@pytest.mark.asyncio
async def test_existing_session_is_silently_validated_and_reused() -> None:
    calls: list[str] = []

    async def record(name: str) -> None:
        calls.append(name)

    coordinator = AuthenticationCoordinator(
        automatic=True,
        state_present=lambda: True,
        reset_session=lambda: record("reset"),
        login=lambda: record("login"),
        validate=lambda: record("validate"),
    )

    coordinator.start()
    await coordinator.ensure_ready()

    assert coordinator.state is SessionAuthenticationState.AUTHENTICATED
    assert calls == ["validate"]


@pytest.mark.asyncio
async def test_expired_saved_session_opens_reauthentication_once_then_revalidates() -> None:
    validations = 0
    calls: list[str] = []

    async def reset() -> None:
        calls.append("reset")

    async def login() -> None:
        calls.append("login")

    async def validate() -> None:
        nonlocal validations
        validations += 1
        calls.append(f"validate-{validations}")
        if validations == 1:
            raise AuthenticationRequiredError("The saved session expired.")

    coordinator = AuthenticationCoordinator(
        automatic=True,
        state_present=lambda: True,
        reset_session=reset,
        login=login,
        validate=validate,
    )

    coordinator.start()
    await coordinator.ensure_ready()

    assert coordinator.state is SessionAuthenticationState.AUTHENTICATED
    assert calls == ["validate-1", "reset", "login", "validate-2"]


@pytest.mark.asyncio
async def test_restriction_requires_attention_and_is_not_retried_as_login() -> None:
    login_calls = 0

    async def login() -> None:
        nonlocal login_calls
        login_calls += 1

    async def validate() -> None:
        raise RestrictionDetectedError("LinkedIn returned a restriction-shaped page.")

    coordinator = AuthenticationCoordinator(
        automatic=True,
        state_present=lambda: True,
        reset_session=login,
        login=login,
        validate=validate,
    )

    coordinator.start()
    with pytest.raises(RestrictionDetectedError, match="restriction-shaped"):
        await coordinator.ensure_ready()

    assert coordinator.state is SessionAuthenticationState.ATTENTION_REQUIRED
    assert login_calls == 0


@pytest.mark.asyncio
async def test_automatic_bootstrap_can_be_disabled_for_headless_deployments() -> None:
    called = False

    async def unexpected() -> None:
        nonlocal called
        called = True

    coordinator = AuthenticationCoordinator(
        automatic=False,
        state_present=lambda: False,
        reset_session=unexpected,
        login=unexpected,
        validate=unexpected,
    )

    coordinator.start()
    await coordinator.ensure_ready()

    assert coordinator.state is SessionAuthenticationState.LOGIN_REQUIRED
    assert called is False
