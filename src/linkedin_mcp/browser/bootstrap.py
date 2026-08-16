"""Managed, package-friendly installation of the official Playwright Chromium."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast

import playwright

from linkedin_mcp.browser.models import BrowserSetupState
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import BrowserUnavailableError

_BROWSER_PREFIXES = {
    "chromium": "chromium-",
    "chromium-headless-shell": "chromium_headless_shell-",
}


class BrowserRuntimeBootstrap:
    """Install and share one Chromium revision outside ephemeral package environments."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._state = (
            BrowserSetupState.NOT_STARTED
            if settings.browser_auto_install
            else BrowserSetupState.DISABLED
        )
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_error: BrowserUnavailableError | None = None

    @property
    def state(self) -> BrowserSetupState:
        return self._state

    @property
    def ready(self) -> bool:
        return self._state in {
            BrowserSetupState.DISABLED,
            BrowserSetupState.READY,
        }

    @property
    def cache_path(self) -> Path:
        configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        return Path(configured).expanduser() if configured else self._settings.browser_cache_path

    def inspect_state(self) -> BrowserSetupState:
        """Refresh installation state without downloading or starting a browser."""

        if not self._settings.browser_auto_install:
            self._state = BrowserSetupState.DISABLED
            return self._state
        self._state = (
            BrowserSetupState.READY if self._installation_ready() else BrowserSetupState.NOT_STARTED
        )
        return self._state

    def start(self) -> None:
        """Schedule browser installation without delaying MCP initialization."""

        if not self._settings.browser_auto_install:
            return
        current = self._task
        if current is not None:
            if not current.done():
                return
            self._consume_task(current)
        self._task = asyncio.create_task(
            self.ensure_ready(),
            name="linkedin-playwright-browser-setup",
        )

    async def ensure_ready(self, *, force: bool = False) -> None:
        """Wait until the configured Chromium revision is installed."""

        if not self._settings.browser_auto_install and not force:
            self._state = BrowserSetupState.DISABLED
            return
        self._configure_environment()
        if self._installation_ready():
            self._state = BrowserSetupState.READY
            self._last_error = None
            return
        current = self._task
        if current is not None and current is not asyncio.current_task() and not current.done():
            await asyncio.shield(current)
            self._raise_if_failed()
            return
        async with self._lock:
            if self._installation_ready():
                self._state = BrowserSetupState.READY
                self._last_error = None
                return
            self._state = BrowserSetupState.INSTALLING
            try:
                await asyncio.to_thread(self._install)
            except BrowserUnavailableError as error:
                self._state = BrowserSetupState.FAILED
                self._last_error = error
                raise
            self._state = BrowserSetupState.READY
            self._last_error = None

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        if task.done():
            self._consume_task(task)
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    def _configure_environment(self) -> None:
        operator_managed = bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
        path = self.cache_path.expanduser().absolute()
        existed = path.exists()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt" and (not operator_managed or not existed):
            path.chmod(0o700)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)

    def _install(self) -> None:
        environment = dict(os.environ)
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(self.cache_path)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=self._settings.browser_install_timeout_seconds,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BrowserUnavailableError(
                "Automatic Chromium setup failed. Run `linkedin-mcp setup` for a direct retry."
            ) from error
        if result.returncode != 0 or not self._installation_ready():
            raise BrowserUnavailableError(
                "Automatic Chromium setup failed. Run `linkedin-mcp setup` for a direct retry."
            )

    def _installation_ready(self) -> bool:
        targets = self._expected_targets()
        if not targets:
            return False
        path = self.cache_path
        return all(
            (path / f"{prefix}{revision}" / "INSTALLATION_COMPLETE").is_file()
            for prefix, revision in targets
        )

    @staticmethod
    def _expected_targets() -> tuple[tuple[str, str], ...]:
        registry_path = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        try:
            decoded: object = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(decoded, dict):
            return ()
        payload = cast(dict[str, object], decoded)
        browsers = payload.get("browsers")
        if not isinstance(browsers, list):
            return ()
        typed_browsers = cast(list[object], browsers)
        targets: list[tuple[str, str]] = []
        for decoded_entry in typed_browsers:
            if not isinstance(decoded_entry, dict):
                continue
            entry = cast(dict[str, object], decoded_entry)
            name = entry.get("name")
            revision = entry.get("revision")
            if not isinstance(name, str) or not isinstance(revision, (str, int)):
                continue
            prefix = _BROWSER_PREFIXES.get(name)
            if prefix is not None:
                targets.append((prefix, str(revision)))
        return tuple(targets)

    def _raise_if_failed(self) -> None:
        if self._last_error is not None:
            raise self._last_error

    @staticmethod
    def _consume_task(task: asyncio.Task[None]) -> None:
        with suppress(asyncio.CancelledError):
            task.exception()
