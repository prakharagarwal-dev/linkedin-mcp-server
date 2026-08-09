"""Environment-backed server configuration with fail-closed validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_path, user_data_path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from linkedin_mcp.domain.models import CapabilityEffect, LinkedInSurface


def default_data_path() -> Path:
    """Return the persistent per-user root for local LinkedIn MCP state."""

    return user_data_path("linkedin-mcp", appauthor=False)


def _default_browser_profile_path() -> Path:
    return default_data_path() / "profile"


def _default_browser_cache_path() -> Path:
    return user_cache_path("ms-playwright", appauthor=False, opinion=False)


def _default_asset_root_path() -> Path:
    return default_data_path() / "assets"


def _default_runtime_lock_path() -> Path:
    return default_data_path() / "runtime.lock"


DEFAULT_ALLOWED_SURFACES: frozenset[LinkedInSurface] = frozenset(
    {
        LinkedInSurface.JOB_SEARCH,
        LinkedInSurface.JOB_DETAIL,
        LinkedInSurface.PEOPLE_SEARCH,
        LinkedInSurface.MEMBER_PROFILE,
        LinkedInSurface.COMPANY_SEARCH,
        LinkedInSurface.COMPANY_PROFILE,
        LinkedInSurface.COMPANY_ABOUT,
        LinkedInSurface.CONTENT_SEARCH,
        LinkedInSurface.POST_DETAIL,
        LinkedInSurface.POST_DISCUSSION,
        LinkedInSurface.POST_COMPOSER,
        LinkedInSurface.MESSAGING,
        LinkedInSurface.CONNECTIONS,
    }
)

DEFAULT_ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        "linkedin.jobs.search",
        "linkedin.jobs.read",
        "linkedin.people.search",
        "linkedin.people.read",
        "linkedin.companies.search",
        "linkedin.companies.read",
        "linkedin.posts.search",
        "linkedin.posts.read",
        "linkedin.posts.comments.read",
        "linkedin.posts.create",
        "linkedin.posts.comments.create",
        "linkedin.posts.reactions.set",
        "linkedin.invitations.read",
        "linkedin.connections.read",
        "linkedin.invitations.send",
        "linkedin.invitations.accept",
        "linkedin.invitations.ignore",
        "linkedin.messaging.read",
        "linkedin.messaging.send",
    }
)

DEFAULT_ALLOWED_EFFECTS: frozenset[CapabilityEffect] = frozenset(CapabilityEffect)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LINKEDIN_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    account_id: str = Field(default="personal", min_length=1, max_length=200)
    browser_profile_path: Path = Field(default_factory=_default_browser_profile_path)
    browser_cache_path: Path = Field(default_factory=_default_browser_cache_path)
    browser_auto_install: bool = True
    browser_install_timeout_seconds: float = Field(default=600, ge=30, le=1_800)
    auto_login_on_start: bool = True
    asset_root_path: Path = Field(default_factory=_default_asset_root_path)

    allowed_hosts: tuple[str, ...] = ("www.linkedin.com", "linkedin.com")
    allowed_surfaces: frozenset[LinkedInSurface] = DEFAULT_ALLOWED_SURFACES
    allowed_scopes: frozenset[str] = DEFAULT_ALLOWED_SCOPES
    allowed_effects: frozenset[CapabilityEffect] = DEFAULT_ALLOWED_EFFECTS

    queue_capacity: int = Field(default=100, ge=1, le=10_000)
    minimum_navigation_interval_seconds: float = Field(default=2.0, ge=0, le=120)
    job_search_max_pages_per_call: int = Field(default=100, ge=1, le=100)
    people_search_max_pages_per_call: int = Field(default=100, ge=1, le=100)
    profile_max_detail_pages_per_call: int = Field(default=20, ge=0, le=50)
    company_search_max_pages_per_call: int = Field(default=100, ge=1, le=100)
    post_search_max_pages_per_call: int = Field(default=100, ge=1, le=100)
    post_comments_max_expansion_rounds_per_call: int = Field(default=20, ge=0, le=100)
    invitations_max_scroll_rounds_per_call: int = Field(default=100, ge=1, le=500)
    connections_max_scroll_rounds_per_call: int = Field(default=100, ge=1, le=500)
    messaging_max_scroll_rounds_per_call: int = Field(default=100, ge=1, le=500)
    pagination_cursor_ttl_seconds: int = Field(default=900, ge=60, le=86_400)
    pagination_max_active_cursors: int = Field(default=64, ge=1, le=1_000)
    pagination_max_seen_items_per_cursor: int = Field(default=5_000, ge=100, le=50_000)
    action_draft_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)
    runtime_lock_path: Path = Field(default_factory=_default_runtime_lock_path)
    runtime_start_timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    browser_headless: bool = True
    browser_timeout_seconds: float = Field(default=20.0, ge=1, le=300)
    login_timeout_seconds: float = Field(default=900.0, ge=30, le=7_200)

    transport: Literal["stdio", "streamable-http"] = "stdio"
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8000, ge=1, le=65_535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(host.strip().lower().rstrip(".") for host in hosts)
        if not normalized or any(not host or "/" in host or ":" in host for host in normalized):
            raise ValueError("allowed_hosts must contain bare DNS hostnames")
        return normalized

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> Settings:
        if self.transport == "streamable-http" and self.http_host not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise ValueError(
                "Unauthenticated Streamable HTTP is restricted to loopback in this release."
            )
        return self


def runtime_configuration_fingerprint(settings: Settings) -> str:
    """Hash the effective shared-runtime policy without exposing local values."""

    values = settings.model_dump(mode="json")
    values["transport"] = "streamable-http"
    values.pop("runtime_start_timeout_seconds", None)
    for field_name in ("allowed_surfaces", "allowed_scopes", "allowed_effects"):
        values[field_name] = sorted(values[field_name])
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
