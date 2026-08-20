"""Local lifecycle for the dedicated persistent Playwright Chromium profile."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from playwright.async_api import async_playwright

from linkedin_mcp.browser.bootstrap import BrowserBootstrap
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import BrowserUnavailableError, ConfigurationError


@dataclass(frozen=True, slots=True)
class BrowserProfileStatus:
    """Non-secret local state for the configured Chromium profile."""

    path: Path
    exists: bool
    initialized: bool


@dataclass(frozen=True, slots=True)
class BrowserProfileResetResult:
    """Result of replacing one profile with a new clean profile."""

    path: Path
    archived_path: Path | None


class BrowserProfileManager:
    """Create, inspect, and recoverably reset one dedicated browser profile."""

    def __init__(
        self,
        settings: Settings,
        browser_bootstrap: BrowserBootstrap | None = None,
    ) -> None:
        self._settings = settings
        self._browser_bootstrap = browser_bootstrap or BrowserBootstrap(settings)

    @property
    def path(self) -> Path:
        return self._settings.browser_profile_path.expanduser().absolute()

    def inspect(self) -> BrowserProfileStatus:
        path = self._validated_path()
        exists = path.is_dir()
        return BrowserProfileStatus(
            path=path,
            exists=exists,
            initialized=exists and any(path.iterdir()),
        )

    def require_initialized(self) -> None:
        status = self.inspect()
        if status.initialized:
            return
        raise ConfigurationError(
            "The persistent Chromium profile has not been created. Run "
            "`linkedin-mcp profile create` first."
        )

    async def create(self) -> bool:
        """Initialize a clean profile, returning false when one already exists."""

        path = self._validated_path()
        if path.exists() and not path.is_dir():
            raise ConfigurationError("The configured browser profile path is not a directory.")
        if path.is_dir() and any(path.iterdir()):
            return False

        await self._browser_bootstrap.ensure_ready()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            path.chmod(0o700)
        playwright = None
        context = None
        try:
            playwright = await async_playwright().start()
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(path),
                headless=True,
            )
        except Exception as error:
            self._archive_failed_creation(path)
            raise BrowserUnavailableError(
                "The persistent Chromium profile could not be created."
            ) from error
        finally:
            if context is not None:
                await context.close()
            if playwright is not None:
                await playwright.stop()
        if not self.inspect().initialized:
            raise BrowserUnavailableError("Chromium did not initialize the configured profile.")
        return True

    async def reset(self) -> BrowserProfileResetResult:
        """Archive the exact profile path and initialize a clean replacement."""

        path = self._validated_path()
        archived_path: Path | None = None
        if path.exists():
            if not path.is_dir():
                raise ConfigurationError("The configured browser profile path is not a directory.")
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            archived_path = path.with_name(f"{path.name}.backup-{stamp}-{uuid4().hex[:8]}")
            try:
                path.rename(archived_path)
            except OSError as error:
                raise ConfigurationError(
                    "The existing Chromium profile could not be archived safely."
                ) from error
        try:
            await self.create()
        except BaseException:
            if archived_path is not None and archived_path.exists():
                if path.exists():
                    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
                    failed_path = path.with_name(f"{path.name}.failed-{stamp}-{uuid4().hex[:8]}")
                    path.rename(failed_path)
                archived_path.rename(path)
            raise
        return BrowserProfileResetResult(path=path, archived_path=archived_path)

    def _validated_path(self) -> Path:
        path = self.path
        if path.is_symlink():
            raise ConfigurationError("The browser profile path cannot be a symbolic link.")
        resolved = path.resolve(strict=False)
        forbidden = {
            Path(resolved.anchor).resolve(),
            Path.home().resolve(),
            Path.cwd().resolve(),
        }
        if resolved in forbidden:
            raise ConfigurationError("The configured browser profile path is too broad to manage.")
        return path

    @staticmethod
    def _archive_failed_creation(path: Path) -> Path | None:
        if not path.exists():
            return None
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        failed_path = path.with_name(f"{path.name}.failed-{stamp}-{uuid4().hex[:8]}")
        try:
            path.rename(failed_path)
        except OSError:
            return None
        return failed_path
