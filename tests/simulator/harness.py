"""Composition root for the stateful, offline MCP workflow simulator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from linkedin_mcp.application import (
    AccountProcessLock,
    CapabilityExecutor,
    CapabilityWorker,
    CompanyProfileProvider,
    CompanySearchProvider,
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
from tests.contract.test_mcp_protocol import (
    ProtocolJobDetail,
    ProtocolPeopleSearch,
    ProtocolPersonProfile,
)
from tests.simulator.providers import StatefulProtocolJobSearch, StatefulProtocolNetwork
from tests.simulator.state import SimulatorState


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
    )
    registry = create_default_registry()
    browser = BrowserManager(settings)
    network = StatefulProtocolNetwork(state)
    executor = CapabilityExecutor(
        settings=settings,
        job_search=StatefulProtocolJobSearch(state),
        job_detail=ProtocolJobDetail(),
        people_search=ProtocolPeopleSearch(),
        person_profile=ProtocolPersonProfile(),
        company_search=cast(CompanySearchProvider, object()),
        company_profile=cast(CompanyProfileProvider, object()),
        post_search=cast(PostSearchProvider, object()),
        post_detail=cast(PostDetailProvider, object()),
        post_comments=cast(PostCommentsProvider, object()),
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
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(settings.runtime_lock_path),
    )
