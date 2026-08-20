from __future__ import annotations

from pathlib import Path

import pytest
from platformdirs import user_cache_path
from pydantic import ValidationError

from linkedin_mcp.config import Settings, default_data_path, runtime_configuration_fingerprint


def test_remote_unauthenticated_http_fails_closed() -> None:
    with pytest.raises(ValidationError, match="restricted to loopback"):
        Settings(transport="streamable-http", http_host="0.0.0.0")


def test_runtime_configuration_fingerprint_ignores_proxy_transport_but_tracks_runtime() -> None:
    base = Settings(transport="stdio")
    equivalent = base.model_copy(
        update={
            "transport": "streamable-http",
            "runtime_start_timeout_seconds": 120,
        }
    )
    changed = base.model_copy(update={"queue_capacity": base.queue_capacity + 1})

    assert runtime_configuration_fingerprint(base) == runtime_configuration_fingerprint(equivalent)
    assert runtime_configuration_fingerprint(base) != runtime_configuration_fingerprint(changed)


def test_local_paths_default_to_persistent_platform_locations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "BROWSER_PROFILE_PATH",
        "BROWSER_CACHE_PATH",
        "RUNTIME_LOCK_PATH",
    ):
        monkeypatch.delenv(f"LINKEDIN_MCP_{name}", raising=False)

    settings = Settings()
    data_path = default_data_path()

    assert settings.browser_profile_path == data_path / "profile"
    assert settings.browser_cache_path == user_cache_path(
        "ms-playwright",
        appauthor=False,
        opinion=False,
    )
    assert settings.runtime_lock_path == data_path / "runtime.lock"


def test_local_queue_and_internal_search_bound_are_validated() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 30"):
        Settings(browser_install_timeout_seconds=29)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(queue_capacity=0)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(job_search_max_pages_per_call=0)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(people_search_max_pages_per_call=0)

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Settings(profile_max_detail_pages_per_call=-1)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(company_search_max_pages_per_call=0)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(post_search_max_pages_per_call=0)

    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        Settings(post_comments_max_expansion_rounds_per_call=-1)

    for field in (
        "invitations_max_scroll_rounds_per_call",
        "connections_max_scroll_rounds_per_call",
        "messaging_max_scroll_rounds_per_call",
    ):
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            Settings.model_validate({field: 0})

    with pytest.raises(ValidationError, match="greater than or equal to 60"):
        Settings(pagination_cursor_ttl_seconds=59)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(pagination_max_active_cursors=0)

    with pytest.raises(ValidationError, match="greater than or equal to 100"):
        Settings(pagination_max_seen_items_per_cursor=99)

    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Settings(runtime_start_timeout_seconds=0.5)

    settings = Settings()
    assert settings.pagination_cursor_ttl_seconds == 900
    assert settings.pagination_max_active_cursors == 64
    assert settings.pagination_max_seen_items_per_cursor == 5_000
    assert settings.runtime_start_timeout_seconds == 30
