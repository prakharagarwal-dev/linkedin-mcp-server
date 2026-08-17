"""Composition root for the stateful, offline MCP workflow simulator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from linkedin_mcp.app import CapabilityWorker
from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.app.executor import (
    CapabilityExecutor,
    CompanyProfileProvider,
    CompanySearchProvider,
    ConnectionsListProvider,
    ConversationReadProvider,
    ConversationSearchProvider,
    InvitationAcceptProvider,
    InvitationIgnoreProvider,
    InvitationListProvider,
    InvitationSendProvider,
    MessageSendProvider,
    PostCommentProvider,
    PostCommentsProvider,
    PostDetailProvider,
    PostPublishingProvider,
    PostReactionProvider,
    PostSearchProvider,
)
from linkedin_mcp.config import Settings
from linkedin_mcp.runtime import AccountProcessLock
from linkedin_mcp.tools._shared.browser import BrowserManager
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
    browser = BrowserManager(settings)
    network = StatefulProtocolNetwork(state)
    people_search = ProtocolPeopleSearch()
    executor = CapabilityExecutor(
        settings=settings,
        job_search=StatefulProtocolJobSearch(state),
        job_detail=ProtocolJobDetail(),
        people_search=people_search,
        connections_search=people_search,
        person_profile=ProtocolPersonProfile(),
        company_search=cast(CompanySearchProvider, object()),
        company_profile=cast(CompanyProfileProvider, object()),
        post_search=cast(PostSearchProvider, object()),
        post_detail=cast(PostDetailProvider, object()),
        post_comments=cast(PostCommentsProvider, object()),
        post_publishing=cast(PostPublishingProvider, network),
        post_comment=cast(PostCommentProvider, network),
        post_reaction=cast(PostReactionProvider, network),
        invitation_list=cast(InvitationListProvider, network),
        connections_list=cast(ConnectionsListProvider, network),
        invitation_send=cast(InvitationSendProvider, network),
        invitation_accept=cast(InvitationAcceptProvider, network),
        invitation_ignore=cast(InvitationIgnoreProvider, network),
        conversation_search=cast(ConversationSearchProvider, network),
        conversation_read=cast(ConversationReadProvider, network),
        message_send=cast(MessageSendProvider, network),
    )
    worker = CapabilityWorker(executor, queue_capacity=settings.queue_capacity)
    return AppContainer(
        settings=settings,
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(settings.runtime_lock_path),
    )
