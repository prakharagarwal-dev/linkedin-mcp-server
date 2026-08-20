"""Public MCP capability implementations and their production wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from linkedin_mcp.browser import BrowserManager
    from linkedin_mcp.config import Settings
    from linkedin_mcp.infra.cursor import CursorStore
    from linkedin_mcp.infra.queue import Scheduler
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


def attach_tools(
    mcp: FastMCP[None],
    *,
    settings: Settings,
    browser: BrowserManager,
    scheduler: Scheduler,
    cursor_store: CursorStore,
) -> None:
    """Construct production pages and attach every public MCP tool."""

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

    conversation_search = ConversationSearchPage(
        browser,
        max_scroll_rounds=settings.messaging_max_scroll_rounds_per_call,
    )
    attach_tool_implementations(
        mcp,
        settings=settings,
        browser=browser,
        scheduler=scheduler,
        cursor_store=cursor_store,
        job_search=JobSearchPage(browser, max_pages=settings.job_search_max_pages_per_call),
        job_detail=JobDetailPage(browser),
        people_search=PeopleSearchPage(
            browser,
            max_pages=settings.people_search_max_pages_per_call,
        ),
        connections_search=ConnectionsSearchPage(
            browser,
            max_pages=settings.people_search_max_pages_per_call,
        ),
        person_profile=PersonProfilePage(
            browser,
            max_detail_pages=settings.profile_max_detail_pages_per_call,
        ),
        company_search=CompanySearchPage(
            browser,
            max_pages=settings.company_search_max_pages_per_call,
        ),
        company_profile=CompanyProfilePage(browser),
        post_search=PostSearchPage(browser, max_pages=settings.post_search_max_pages_per_call),
        post_detail=PostDetailPage(browser),
        post_comments=PostCommentsPage(
            browser,
            max_expansion_rounds=settings.post_comments_max_expansion_rounds_per_call,
        ),
        post_publishing=PostPublishingPage(browser),
        post_comment=PostCommentPage(browser),
        post_reaction=PostReactionPage(browser),
        invitation_list=InvitationListPage(
            browser,
            max_scroll_rounds=settings.invitations_max_scroll_rounds_per_call,
        ),
        connections_list=ConnectionsListPage(
            browser,
            max_scroll_rounds=settings.connections_max_scroll_rounds_per_call,
        ),
        invitation_send=SendInvitationPage(browser),
        invitation_accept=AcceptInvitationPage(browser),
        invitation_ignore=IgnoreInvitationPage(browser),
        conversation_search=conversation_search,
        conversation_read=ConversationGetPage(
            browser,
            conversation_search=conversation_search,
            max_history_rounds=settings.messaging_max_scroll_rounds_per_call,
        ),
        message_send=MessageSendPage(
            browser,
            conversation_search=conversation_search,
            max_history_rounds=settings.messaging_max_scroll_rounds_per_call,
        ),
    )


def attach_tool_implementations(
    mcp: FastMCP[None],
    *,
    settings: Settings,
    browser: BrowserManager,
    scheduler: Scheduler,
    cursor_store: CursorStore,
    job_search: JobSearchPage,
    job_detail: JobDetailPage,
    people_search: PeopleSearchPage,
    connections_search: ConnectionsSearchPage,
    person_profile: PersonProfilePage,
    company_search: CompanySearchPage,
    company_profile: CompanyProfilePage,
    post_search: PostSearchPage,
    post_detail: PostDetailPage,
    post_comments: PostCommentsPage,
    post_publishing: PostPublishingPage,
    post_comment: PostCommentPage,
    post_reaction: PostReactionPage,
    invitation_list: InvitationListPage,
    connections_list: ConnectionsListPage,
    invitation_send: SendInvitationPage,
    invitation_accept: AcceptInvitationPage,
    invitation_ignore: IgnoreInvitationPage,
    conversation_search: ConversationSearchPage,
    conversation_read: ConversationGetPage,
    message_send: MessageSendPage,
) -> None:
    """Attach explicitly supplied tool implementations without storing them."""

    from linkedin_mcp.tools.companies.get.tool import register as register_companies_get
    from linkedin_mcp.tools.companies.search.tool import register as register_companies_search
    from linkedin_mcp.tools.connections.list.tool import register as register_connections_list
    from linkedin_mcp.tools.connections.search.tool import register as register_connections_search
    from linkedin_mcp.tools.invitations.accept.tool import register as register_invitations_accept
    from linkedin_mcp.tools.invitations.ignore.tool import register as register_invitations_ignore
    from linkedin_mcp.tools.invitations.list.tool import register as register_invitations_list
    from linkedin_mcp.tools.invitations.send.tool import register as register_invitations_send
    from linkedin_mcp.tools.jobs.get.tool import register as register_jobs_get
    from linkedin_mcp.tools.jobs.search.tool import register as register_jobs_search
    from linkedin_mcp.tools.messaging.conversation.get.tool import (
        register as register_messaging_conversation_get,
    )
    from linkedin_mcp.tools.messaging.search.tool import register as register_messaging_search
    from linkedin_mcp.tools.messaging.send.tool import register as register_messaging_send
    from linkedin_mcp.tools.people.get.tool import register as register_people_get
    from linkedin_mcp.tools.people.search.tool import register as register_people_search
    from linkedin_mcp.tools.posts.comment.tool import register as register_posts_comment
    from linkedin_mcp.tools.posts.comments.list.tool import register as register_posts_comments_list
    from linkedin_mcp.tools.posts.create.tool import register as register_posts_create
    from linkedin_mcp.tools.posts.get.tool import register as register_posts_get
    from linkedin_mcp.tools.posts.react.tool import register as register_posts_react
    from linkedin_mcp.tools.posts.search.tool import register as register_posts_search
    from linkedin_mcp.tools.server.status.tool import register as register_server_status
    from linkedin_mcp.tools.session.status.tool import register as register_session_status

    account_id = settings.account_id
    register_server_status(mcp, settings, scheduler)
    register_session_status(mcp, settings, browser)
    register_jobs_search(mcp, scheduler, job_search, cursor_store, account_id)
    register_jobs_get(mcp, scheduler, job_detail)
    register_people_search(mcp, scheduler, people_search, cursor_store, account_id)
    register_people_get(mcp, scheduler, person_profile)
    register_companies_search(mcp, scheduler, company_search, cursor_store, account_id)
    register_companies_get(mcp, scheduler, company_profile)
    register_posts_search(mcp, scheduler, post_search, cursor_store, account_id)
    register_posts_get(mcp, scheduler, post_detail)
    register_posts_comments_list(mcp, scheduler, post_comments, cursor_store, account_id)
    register_posts_create(mcp, scheduler, post_publishing)
    register_posts_comment(mcp, scheduler, post_comment)
    register_posts_react(mcp, scheduler, post_reaction)
    register_invitations_list(mcp, scheduler, invitation_list, cursor_store, account_id)
    register_connections_list(mcp, scheduler, connections_list, cursor_store, account_id)
    register_connections_search(mcp, scheduler, connections_search, cursor_store, account_id)
    register_invitations_send(mcp, scheduler, invitation_send)
    register_invitations_accept(mcp, scheduler, invitation_accept)
    register_invitations_ignore(mcp, scheduler, invitation_ignore)
    register_messaging_search(mcp, scheduler, conversation_search, cursor_store, account_id)
    register_messaging_conversation_get(mcp, scheduler, conversation_read)
    register_messaging_send(mcp, scheduler, message_send)
