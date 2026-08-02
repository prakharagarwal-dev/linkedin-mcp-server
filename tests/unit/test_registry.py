from __future__ import annotations

from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.models import (
    CapabilityEffect,
    CapabilityName,
    LinkedInSurface,
)


def test_registry_reports_enabled_read_capabilities() -> None:
    settings = Settings()
    registry = create_default_registry()

    assert registry.get(CapabilityName.JOBS_SEARCH).status(settings).enabled is True
    assert registry.get(CapabilityName.JOBS_GET).status(settings).enabled is True
    assert registry.get(CapabilityName.PEOPLE_SEARCH).status(settings).enabled is True
    assert registry.get(CapabilityName.PEOPLE_GET).status(settings).enabled is True
    assert registry.get(CapabilityName.COMPANIES_SEARCH).status(settings).enabled is False
    assert registry.get(CapabilityName.COMPANIES_GET).status(settings).enabled is False
    assert registry.get(CapabilityName.INVITATIONS_LIST).status(settings).enabled is False
    assert registry.get(CapabilityName.MESSAGING_MESSAGE_EXECUTE).status(settings).enabled is False

    assert {descriptor.name for descriptor in registry.list()} == set(CapabilityName)


def test_company_reads_require_explicit_search_and_profile_contracts() -> None:
    settings = Settings(
        allowed_surfaces=frozenset(
            {
                LinkedInSurface.COMPANY_SEARCH,
                LinkedInSurface.COMPANY_PROFILE,
                LinkedInSurface.COMPANY_ABOUT,
            }
        ),
        allowed_scopes=frozenset(
            {
                "linkedin.companies.search",
                "linkedin.companies.read",
            }
        ),
    )
    registry = create_default_registry()

    assert registry.get(CapabilityName.COMPANIES_SEARCH).status(settings).enabled is True
    assert registry.get(CapabilityName.COMPANIES_GET).status(settings).enabled is True


def test_post_reads_require_each_exact_surface_and_scope() -> None:
    settings = Settings(
        allowed_surfaces=frozenset(
            {
                LinkedInSurface.CONTENT_SEARCH,
                LinkedInSurface.POST_DETAIL,
                LinkedInSurface.POST_DISCUSSION,
            }
        ),
        allowed_scopes=frozenset(
            {
                "linkedin.posts.search",
                "linkedin.posts.read",
                "linkedin.posts.comments.read",
            }
        ),
    )
    registry = create_default_registry()

    for name in (
        CapabilityName.POSTS_SEARCH,
        CapabilityName.POSTS_GET,
        CapabilityName.POST_COMMENTS_LIST,
    ):
        assert registry.get(name).status(settings).enabled is True

    missing_discussion = settings.model_copy(
        update={"allowed_surfaces": settings.allowed_surfaces - {LinkedInSurface.POST_DISCUSSION}}
    )
    status = registry.get(CapabilityName.POST_COMMENTS_LIST).status(missing_discussion)
    assert status.enabled is False
    assert status.disabled_reason is not None
    assert "post-discussion" in status.disabled_reason


def test_invitations_connections_and_messaging_have_independent_scopes() -> None:
    settings = Settings(
        allowed_surfaces=frozenset(LinkedInSurface),
        allowed_scopes=frozenset(
            {
                "linkedin.people.search",
                "linkedin.connections.read",
                "linkedin.invitations.read",
                "linkedin.invitations.send",
                "linkedin.invitations.accept",
                "linkedin.invitations.ignore",
                "linkedin.messaging.read",
                "linkedin.messaging.send",
            }
        ),
        allowed_effects=frozenset(CapabilityEffect),
    )
    registry = create_default_registry()

    for name in (
        CapabilityName.INVITATIONS_LIST,
        CapabilityName.CONNECTIONS_LIST,
        CapabilityName.CONNECTIONS_SEARCH,
        CapabilityName.INVITATION_SEND_PREPARE,
        CapabilityName.INVITATION_SEND_EXECUTE,
        CapabilityName.INVITATION_ACCEPT_PREPARE,
        CapabilityName.INVITATION_ACCEPT_EXECUTE,
        CapabilityName.INVITATION_IGNORE_PREPARE,
        CapabilityName.INVITATION_IGNORE_EXECUTE,
        CapabilityName.MESSAGING_SEARCH,
        CapabilityName.MESSAGING_CONVERSATION_GET,
        CapabilityName.MESSAGING_MESSAGE_PREPARE,
        CapabilityName.MESSAGING_MESSAGE_EXECUTE,
    ):
        assert registry.get(name).status(settings).enabled is True

    without_connections_surface = settings.model_copy(
        update={
            "allowed_surfaces": settings.allowed_surfaces - frozenset({LinkedInSurface.CONNECTIONS})
        }
    )
    assert (
        registry.get(CapabilityName.INVITATION_SEND_PREPARE)
        .status(without_connections_surface)
        .enabled
        is True
    )
    assert (
        registry.get(CapabilityName.INVITATION_SEND_EXECUTE)
        .status(without_connections_surface)
        .enabled
        is True
    )

    without_invitation_read = settings.model_copy(
        update={
            "allowed_scopes": settings.allowed_scopes - frozenset({"linkedin.invitations.read"})
        }
    )
    invitation_list_status = registry.get(CapabilityName.INVITATIONS_LIST).status(
        without_invitation_read
    )
    assert invitation_list_status.enabled is False
    assert invitation_list_status.disabled_reason is not None
    assert "linkedin.invitations.read" in invitation_list_status.disabled_reason
    assert (
        registry.get(CapabilityName.CONNECTIONS_LIST).status(without_invitation_read).enabled
        is True
    )
    assert (
        registry.get(CapabilityName.CONNECTIONS_SEARCH).status(without_invitation_read).enabled
        is True
    )

    without_ignore_scope = settings.model_copy(
        update={
            "allowed_scopes": settings.allowed_scopes - frozenset({"linkedin.invitations.ignore"})
        }
    )
    assert (
        registry.get(CapabilityName.INVITATION_ACCEPT_EXECUTE).status(without_ignore_scope).enabled
        is True
    )
    ignore_status = registry.get(CapabilityName.INVITATION_IGNORE_EXECUTE).status(
        without_ignore_scope
    )
    assert ignore_status.enabled is False
    assert ignore_status.disabled_reason is not None
    assert "linkedin.invitations.ignore" in ignore_status.disabled_reason


def test_personal_post_prepare_and_execute_require_independent_effect_authorization() -> None:
    base = Settings(
        allowed_surfaces=frozenset({LinkedInSurface.POST_COMPOSER}),
        allowed_scopes=frozenset({"linkedin.posts.create"}),
        allowed_effects=frozenset({CapabilityEffect.PREPARE}),
    )
    registry = create_default_registry()

    assert registry.get(CapabilityName.POSTS_CREATE_PREPARE).status(base).enabled is True
    execute_status = registry.get(CapabilityName.POSTS_CREATE_EXECUTE).status(base)
    assert execute_status.enabled is False
    assert execute_status.disabled_reason is not None
    assert "effect write" in execute_status.disabled_reason

    fully_authorized = base.model_copy(
        update={"allowed_effects": frozenset({CapabilityEffect.PREPARE, CapabilityEffect.WRITE})}
    )
    assert (
        registry.get(CapabilityName.POSTS_CREATE_EXECUTE).status(fully_authorized).enabled is True
    )
