"""Non-blocking first-run and reauthentication session coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog

from linkedin_mcp.domain.models import SessionAuthenticationState
from linkedin_mcp.errors import (
    AuthenticationRequiredError,
    BrowserUnavailableError,
    LinkedInMCPError,
)

logger = structlog.get_logger(__name__)

AsyncStep = Callable[[], Awaitable[None]]
StatePresent = Callable[[], bool]


class AuthenticationCoordinator:
    """Run login and validation in the background while MCP remains responsive."""

    def __init__(
        self,
        *,
        automatic: bool,
        state_present: StatePresent,
        reset_session: AsyncStep,
        login: AsyncStep,
        validate: AsyncStep,
    ) -> None:
        self._automatic = automatic
        self._state_present = state_present
        self._reset_session = reset_session
        self._login = login
        self._validate = validate
        self._task: asyncio.Task[None] | None = None
        self._last_error: LinkedInMCPError | None = None
        self._status_message: str | None = None
        if state_present():
            self._state = SessionAuthenticationState.UNVERIFIED
        else:
            self._state = SessionAuthenticationState.LOGIN_REQUIRED

    @property
    def automatic(self) -> bool:
        return self._automatic

    @property
    def state(self) -> SessionAuthenticationState:
        return self._state

    @property
    def status_message(self) -> str | None:
        return self._status_message

    @property
    def login_browser_open(self) -> bool:
        return self._state is SessionAuthenticationState.LOGIN_IN_PROGRESS

    def start(self) -> None:
        """Schedule startup validation/login without delaying MCP initialization."""

        if self._automatic:
            self._schedule(force_login=False)

    async def ensure_ready(self) -> None:
        """Wait for an already scheduled automatic bootstrap before browser work."""

        if not self._automatic:
            return
        if self._is_authenticated():
            return
        if self._state is not SessionAuthenticationState.ATTENTION_REQUIRED:
            self._schedule(force_login=False)
        task = self._task
        if task is not None and not task.done():
            await asyncio.shield(task)
        if self._is_authenticated():
            return
        if self._last_error is not None:
            raise self._last_error
        raise AuthenticationRequiredError(
            self._status_message or "LinkedIn authentication requires operator attention."
        )

    def request_reauthentication(self, reason: str) -> None:
        """Pause new work and open one headed reauthentication flow."""

        self._state = SessionAuthenticationState.LOGIN_REQUIRED
        self._status_message = reason
        self._last_error = None
        if self._automatic:
            self._schedule(force_login=True)

    def mark_authenticated(self) -> None:
        self._state = SessionAuthenticationState.AUTHENTICATED
        self._status_message = None
        self._last_error = None

    def mark_attention_required(self, error: LinkedInMCPError) -> None:
        self._state = SessionAuthenticationState.ATTENTION_REQUIRED
        self._status_message = error.safe_message
        self._last_error = error

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _is_authenticated(self) -> bool:
        return self._state is SessionAuthenticationState.AUTHENTICATED

    def _schedule(self, *, force_login: bool) -> None:
        current = self._task
        if current is not None and not current.done():
            return
        self._task = asyncio.create_task(
            self._run(force_login=force_login),
            name="linkedin-session-authentication",
        )

    async def _run(self, *, force_login: bool) -> None:
        logged_in = False
        try:
            if force_login or not self._state_present():
                await self._run_login()
                logged_in = True
            try:
                await self._run_validation()
            except AuthenticationRequiredError:
                if logged_in:
                    raise
                await self._run_login()
                await self._run_validation()
        except asyncio.CancelledError:
            raise
        except LinkedInMCPError as error:
            self.mark_attention_required(error)
            logger.warning(
                "linkedin_session_authentication_attention_required",
                error_code=error.code.value,
                error_type=type(error).__name__,
            )
        except Exception as error:
            safe_error = BrowserUnavailableError(
                "The automatic LinkedIn authentication flow failed unexpectedly."
            )
            self.mark_attention_required(safe_error)
            logger.warning(
                "linkedin_session_authentication_failed",
                error_type=type(error).__name__,
            )

    async def _run_login(self) -> None:
        await self._reset_session()
        self._state = SessionAuthenticationState.LOGIN_IN_PROGRESS
        self._status_message = (
            "Complete LinkedIn login and any verification in the opened browser window."
        )
        self._last_error = None
        logger.info("linkedin_session_login_browser_opened")
        await self._login()

    async def _run_validation(self) -> None:
        self._state = SessionAuthenticationState.VALIDATING
        self._status_message = "Validating the saved LinkedIn session."
        await self._validate()
        self.mark_authenticated()
        logger.info("linkedin_session_authenticated")
