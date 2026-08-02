"""Composition root for the stateful, offline MCP workflow simulator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from linkedin_mcp.application import (
    AccountProcessLock,
    CapabilityExecutor,
    CapabilityWorker,
    ConnectionsListProvider,
    ConversationProvider,
    ConversationSearchProvider,
    InvitationActionProvider,
    InvitationListProvider,
    PostCommentsProvider,
    PostDetailProvider,
    PostEngagementProvider,
    PostPublishingProvider,
    PostSearchProvider,
)
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.container import AppContainer
from linkedin_mcp.domain.models import CapabilityEffect, LinkedInSurface
from linkedin_mcp.persistence import MemoryRepository
from tests.contract.test_mcp_protocol import (
    ProtocolCompanyProfile,
    ProtocolCompanySearch,
    ProtocolJobDetail,
    ProtocolPeopleSearch,
    ProtocolPersonProfile,
    ProtocolPostComments,
    ProtocolPostDetail,
    ProtocolPostSearch,
)
from tests.simulator.providers import StatefulProtocolJobSearch, StatefulProtocolNetwork
from tests.simulator.state import SimulatorState

ALL_SCOPES = frozenset(
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
        "linkedin.posts.comments.create",
        "linkedin.posts.reactions.set",
        "linkedin.posts.create",
        "linkedin.connections.read",
        "linkedin.invitations.read",
        "linkedin.invitations.send",
        "linkedin.invitations.accept",
        "linkedin.invitations.ignore",
        "linkedin.messaging.read",
        "linkedin.messaging.send",
    }
)


def create_simulator_container(
    root: Path,
    state: SimulatorState,
) -> AppContainer:
    suffix = uuid.uuid4().hex
    settings = Settings(
        auto_login_on_start=False,
        browser_auto_install=False,
        browser_profile_path=root / f"profile-{suffix}",
        asset_root_path=root / f"assets-{suffix}",
        minimum_navigation_interval_seconds=0,
        runtime_lock_path=root / f"runtime-{suffix}.lock",
        allowed_surfaces=frozenset(LinkedInSurface),
        allowed_scopes=ALL_SCOPES,
        allowed_effects=frozenset(CapabilityEffect),
    )
    repository = MemoryRepository()
    registry = create_default_registry()
    browser = BrowserManager(settings)
    network = StatefulProtocolNetwork(state)
    executor = CapabilityExecutor(
        settings=settings,
        registry=registry,
        repository=repository,
        job_search=StatefulProtocolJobSearch(state),
        job_detail=ProtocolJobDetail(),
        people_search=ProtocolPeopleSearch(),
        person_profile=ProtocolPersonProfile(),
        company_search=ProtocolCompanySearch(),
        company_profile=ProtocolCompanyProfile(),
        post_search=cast(PostSearchProvider, ProtocolPostSearch()),
        post_detail=cast(PostDetailProvider, ProtocolPostDetail()),
        post_comments=cast(PostCommentsProvider, ProtocolPostComments()),
        post_publishing=cast(PostPublishingProvider, network),
        post_engagement=cast(PostEngagementProvider, network),
        invitation_list=cast(InvitationListProvider, network),
        connections_list=cast(ConnectionsListProvider, network),
        invitation_actions=cast(InvitationActionProvider, network),
        conversation_search=cast(ConversationSearchProvider, network),
        conversation=cast(ConversationProvider, network),
    )
    worker = CapabilityWorker(executor, queue_capacity=settings.queue_capacity)
    return AppContainer(
        settings=settings,
        registry=registry,
        repository=repository,
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(settings.runtime_lock_path),
    )
