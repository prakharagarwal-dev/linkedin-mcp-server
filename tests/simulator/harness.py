"""Composition root for the stateful, offline MCP workflow simulator."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

from mcp.server.fastmcp import FastMCP

from linkedin_mcp.config import Settings
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Worker
from linkedin_mcp.tools import attach_tool_implementations
from linkedin_mcp.tools.companies.get.page import CompanyProfilePage
from linkedin_mcp.tools.companies.search.page import CompanySearchPage
from linkedin_mcp.tools.connections.list.page import ConnectionsListPage
from linkedin_mcp.tools.connections.search.page import ConnectionsSearchPage
from linkedin_mcp.tools.invitations.accept.page import AcceptInvitationPage
from linkedin_mcp.tools.invitations.ignore.page import IgnoreInvitationPage
from linkedin_mcp.tools.invitations.list.page import InvitationListPage
from linkedin_mcp.tools.invitations.send.page import SendInvitationPage
from linkedin_mcp.tools.jobs.get.page import JobDetailPage
from linkedin_mcp.tools.jobs.search.page import JobSearchPage
from linkedin_mcp.tools.messaging.conversation.get.page import ConversationGetPage
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage
from linkedin_mcp.tools.messaging.send.page import MessageSendPage
from linkedin_mcp.tools.people.get.page import PersonProfilePage
from linkedin_mcp.tools.people.search.page import PeopleSearchPage
from linkedin_mcp.tools.posts.comment.page import PostCommentPage
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.create.page import PostPublishingPage
from linkedin_mcp.tools.posts.get.page import PostDetailPage
from linkedin_mcp.tools.posts.react.page import PostReactionPage
from linkedin_mcp.tools.posts.search.page import PostSearchPage
from linkedin_mcp.transport.server import create_mcp_server
from linkedin_mcp.ui import LinkedInPlaywright
from tests.contract.test_mcp_protocol import (
    ProtocolJobDetail,
    ProtocolPeopleSearch,
    ProtocolPersonProfile,
)
from tests.simulator.providers import StatefulProtocolJobSearch, StatefulProtocolNetwork
from tests.simulator.state import SimulatorState
from tests.support.playwright import empty_playwright


def create_simulator_server(
    root: Path,
    state: SimulatorState,
) -> tuple[FastMCP[None], Scheduler, LinkedInPlaywright, CursorStore]:
    suffix = uuid.uuid4().hex
    settings = Settings(
        browser_auto_install=False,
        browser_profile_path=root / f"profile-{suffix}",
        minimum_navigation_interval_seconds=0,
        runtime_lock_path=root / f"runtime-{suffix}.lock",
    )
    playwright = empty_playwright(settings)
    network = StatefulProtocolNetwork(state)
    people_search = ProtocolPeopleSearch()
    cursor_store = CursorStore(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )
    worker = Worker()
    scheduler = Scheduler(worker, capacity=settings.queue_capacity)
    mcp = create_mcp_server(settings)
    attach_tool_implementations(
        mcp,
        settings=settings,
        playwright=playwright,
        scheduler=scheduler,
        cursor_store=cursor_store,
        job_search=cast(JobSearchPage, StatefulProtocolJobSearch(state)),
        job_detail=cast(JobDetailPage, ProtocolJobDetail()),
        people_search=cast(PeopleSearchPage, people_search),
        connections_search=cast(ConnectionsSearchPage, people_search),
        person_profile=cast(PersonProfilePage, ProtocolPersonProfile()),
        company_search=cast(CompanySearchPage, object()),
        company_profile=cast(CompanyProfilePage, object()),
        post_search=cast(PostSearchPage, object()),
        post_detail=cast(PostDetailPage, object()),
        post_comments=cast(PostCommentsPage, object()),
        post_publishing=cast(PostPublishingPage, network),
        post_comment=cast(PostCommentPage, network),
        post_reaction=cast(PostReactionPage, network),
        invitation_list=cast(InvitationListPage, network),
        connections_list=cast(ConnectionsListPage, network),
        invitation_send=cast(SendInvitationPage, network),
        invitation_accept=cast(AcceptInvitationPage, network),
        invitation_ignore=cast(IgnoreInvitationPage, network),
        conversation_search=cast(ConversationSearchPage, network),
        conversation_read=cast(ConversationGetPage, network),
        message_send=cast(MessageSendPage, network),
    )
    return mcp, scheduler, playwright, cursor_store
