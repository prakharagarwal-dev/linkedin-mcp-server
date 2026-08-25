from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import linkedin_mcp.config as config_module
from linkedin_mcp.config import Settings


def test_settings_use_managed_user_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def data_path(_: str, *, appauthor: bool) -> Path:
        del appauthor
        return tmp_path / "data"

    def cache_path(_: str, *, appauthor: bool, opinion: bool) -> Path:
        del appauthor, opinion
        return tmp_path / "cache"

    monkeypatch.setattr(config_module, "user_data_path", data_path)
    monkeypatch.setattr(config_module, "user_cache_path", cache_path)

    settings = Settings()

    assert settings.browser_profile_path == tmp_path / "data" / "profile"
    assert settings.browser_cache_path == tmp_path / "cache"


def test_settings_load_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINKEDIN_MCP_HTTP_PORT", "8123")
    monkeypatch.setenv("LINKEDIN_MCP_BROWSER_HEADLESS", "false")
    monkeypatch.setenv("LINKEDIN_MCP_ALLOWED_HOSTS", '["www.linkedin.com"]')

    settings = Settings()

    assert settings.http_port == 8123
    assert settings.browser_headless is False
    assert settings.allowed_hosts == ("www.linkedin.com",)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "0.0.0.0"])
def test_settings_accept_http_bind_hosts(host: str) -> None:
    assert Settings(http_host=host).http_host == host


def test_settings_reject_empty_http_host() -> None:
    with pytest.raises(ValidationError):
        Settings(http_host="")


@pytest.mark.parametrize("host", ["", "www.linkedin.com/path", "localhost:443"])
def test_settings_reject_invalid_linkedin_hosts(host: str) -> None:
    with pytest.raises(ValidationError, match="bare DNS hostnames"):
        Settings(allowed_hosts=(host,))


def test_settings_normalize_linkedin_hosts() -> None:
    assert Settings(allowed_hosts=("WWW.LinkedIn.COM.",)).allowed_hosts == ("www.linkedin.com",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("http_port", 0),
        ("browser_action_delay_seconds", -1),
        ("browser_timeout_seconds", 0),
        ("pagination_cursor_ttl_seconds", 1),
        ("pagination_max_active_cursors", 0),
    ],
)
def test_settings_reject_invalid_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_settings_no_longer_contain_transport_or_host_runtime_configuration() -> None:
    fields = Settings.model_fields

    assert "transport" not in fields
    assert "queue_capacity" not in fields
    assert "runtime_lock_path" not in fields
    assert "runtime_start_timeout_seconds" not in fields
