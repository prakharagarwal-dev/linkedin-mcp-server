from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, cast

import pytest

import linkedin_mcp.browser.profile as profile_module
from linkedin_mcp.browser import BrowserBootstrap, BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import BrowserUnavailableError, ConfigurationError


class FakeBootstrap:
    def __init__(self) -> None:
        self.calls = 0

    async def ensure_ready(self) -> None:
        self.calls += 1


class FakeContext:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.launches: list[tuple[Path, bool]] = []
        self.contexts: list[FakeContext] = []

    async def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
    ) -> FakeContext:
        path = Path(user_data_dir)
        self.launches.append((path, headless))
        await asyncio.to_thread(path.mkdir, parents=True, exist_ok=True)
        marker = "Failed" if self.fail else "Preferences"
        await asyncio.to_thread((path / marker).write_text, "{}", encoding="utf-8")
        if self.fail:
            raise RuntimeError("synthetic launch failure")
        context = FakeContext()
        self.contexts.append(context)
        return context


class FakePlaywright:
    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeStarter:
    def __init__(self, playwright: FakePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakePlaywright:
        return self.playwright


def _manager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail: bool = False,
) -> tuple[BrowserProfileManager, FakeBootstrap, FakeChromium, FakePlaywright]:
    settings = Settings(browser_profile_path=tmp_path / "profile")
    bootstrap = FakeBootstrap()
    chromium = FakeChromium(fail=fail)
    playwright = FakePlaywright(chromium)
    monkeypatch.setattr(
        profile_module,
        "async_playwright",
        cast(Any, lambda: FakeStarter(playwright)),
    )
    manager = BrowserProfileManager(
        settings,
        cast(BrowserBootstrap, bootstrap),
    )
    return manager, bootstrap, chromium, playwright


@pytest.mark.asyncio
async def test_profile_create_is_bounded_private_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, bootstrap, chromium, playwright = _manager(tmp_path, monkeypatch)

    assert manager.inspect().exists is False
    with pytest.raises(ConfigurationError, match="profile create"):
        manager.require_initialized()

    assert await manager.create() is True
    assert await manager.create() is False
    status = manager.inspect()

    assert status.exists is True
    assert status.initialized is True
    assert bootstrap.calls == 1
    assert chromium.launches == [(manager.path, True)]
    assert chromium.contexts[0].closed is True
    assert playwright.stopped is True
    if os.name != "nt":
        assert manager.path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
async def test_profile_reset_archives_old_profile_and_creates_clean_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _, _, _ = _manager(tmp_path, monkeypatch)
    manager.path.mkdir(parents=True)
    (manager.path / "old-session").write_text("sensitive", encoding="utf-8")

    result = await manager.reset()

    assert result.path == manager.path
    assert result.archived_path is not None
    assert result.archived_path.parent == manager.path.parent
    assert result.archived_path.name.startswith("profile.backup-")
    assert (result.archived_path / "old-session").read_text(encoding="utf-8") == "sensitive"
    assert (manager.path / "Preferences").is_file()
    assert not (manager.path / "old-session").exists()


@pytest.mark.asyncio
async def test_profile_reset_rolls_back_when_replacement_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _, _, _ = _manager(tmp_path, monkeypatch, fail=True)
    manager.path.mkdir(parents=True)
    (manager.path / "old-session").write_text("preserve-me", encoding="utf-8")

    with pytest.raises(BrowserUnavailableError, match="could not be created"):
        await manager.reset()

    assert (manager.path / "old-session").read_text(encoding="utf-8") == "preserve-me"
    assert not (manager.path / "Failed").exists()
    failed_profiles = tuple(manager.path.parent.glob("profile.failed-*"))
    assert len(failed_profiles) == 1
    assert (failed_profiles[0] / "Failed").is_file()


def test_profile_manager_rejects_broad_or_symbolic_paths(
    tmp_path: Path,
) -> None:
    broad = BrowserProfileManager(Settings(browser_profile_path=Path.cwd()))
    with pytest.raises(ConfigurationError, match="too broad"):
        broad.inspect()

    target = tmp_path / "target"
    target.mkdir()
    linked = tmp_path / "linked-profile"
    linked.symlink_to(target, target_is_directory=True)
    symbolic = BrowserProfileManager(Settings(browser_profile_path=linked))
    with pytest.raises(ConfigurationError, match="symbolic link"):
        symbolic.inspect()
