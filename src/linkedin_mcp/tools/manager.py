"""Construct and register every typed LinkedIn MCP tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from linkedin_mcp.browser import BrowserManager
    from linkedin_mcp.config import Settings
    from linkedin_mcp.cursors import CursorManager
    from linkedin_mcp.operations import OperationManager
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
    from linkedin_mcp.ui.manager import UIManager


class ToolManager:
    """Wire application-scoped dependencies into FastMCP tool definitions."""

    def __init__(
        self,
        mcp: FastMCP[None],
        *,
        settings: Settings,
        browser: BrowserManager,
        ui: UIManager,
        operations: OperationManager,
        cursors: CursorManager,
    ) -> None:
        self._mcp = mcp
        self._settings = settings
        self._browser = browser
        self._ui = ui
        self._operations = operations
        self._cursors = cursors

    def register_all(self) -> None:
        """Construct production page objects and register all public tools."""

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

        settings = self._settings
        ui = self._ui
        conversation_search = ConversationSearchPage(
            ui,
            max_scroll_rounds=settings.messaging_max_scroll_rounds_per_call,
        )
        self.register_implementations(
            job_search=JobSearchPage(ui, max_pages=settings.job_search_max_pages_per_call),
            job_detail=JobDetailPage(ui),
            people_search=PeopleSearchPage(
                ui,
                max_pages=settings.people_search_max_pages_per_call,
            ),
            connections_search=ConnectionsSearchPage(
                ui,
                max_pages=settings.people_search_max_pages_per_call,
            ),
            person_profile=PersonProfilePage(
                ui,
                max_detail_pages=settings.profile_max_detail_pages_per_call,
            ),
            company_search=CompanySearchPage(
                ui,
                max_pages=settings.company_search_max_pages_per_call,
            ),
            company_profile=CompanyProfilePage(ui),
            post_search=PostSearchPage(ui, max_pages=settings.post_search_max_pages_per_call),
            post_detail=PostDetailPage(ui),
            post_comments=PostCommentsPage(
                ui,
                max_expansion_rounds=settings.post_comments_max_expansion_rounds_per_call,
            ),
            post_publishing=PostPublishingPage(ui),
            post_comment=PostCommentPage(ui),
            post_reaction=PostReactionPage(ui),
            invitation_list=InvitationListPage(
                ui,
                max_scroll_rounds=settings.invitations_max_scroll_rounds_per_call,
            ),
            connections_list=ConnectionsListPage(
                ui,
                max_scroll_rounds=settings.connections_max_scroll_rounds_per_call,
            ),
            invitation_send=SendInvitationPage(ui),
            invitation_accept=AcceptInvitationPage(ui),
            invitation_ignore=IgnoreInvitationPage(ui),
            conversation_search=conversation_search,
            conversation_read=ConversationGetPage(
                ui,
                conversation_search=conversation_search,
                max_history_rounds=settings.messaging_max_scroll_rounds_per_call,
            ),
            message_send=MessageSendPage(
                ui,
                conversation_search=conversation_search,
                max_history_rounds=settings.messaging_max_scroll_rounds_per_call,
            ),
        )

    def register_implementations(
        self,
        *,
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
        """Register explicitly supplied implementations, including offline fixtures."""

        from linkedin_mcp.tools.companies.get.tool import register as register_companies_get
        from linkedin_mcp.tools.companies.search.tool import register as register_companies_search
        from linkedin_mcp.tools.connections.list.tool import register as register_connections_list
        from linkedin_mcp.tools.connections.search.tool import (
            register as register_connections_search,
        )
        from linkedin_mcp.tools.invitations.accept.tool import register as register_accept
        from linkedin_mcp.tools.invitations.ignore.tool import register as register_ignore
        from linkedin_mcp.tools.invitations.list.tool import register as register_invitations_list
        from linkedin_mcp.tools.invitations.send.tool import register as register_send
        from linkedin_mcp.tools.jobs.get.tool import register as register_jobs_get
        from linkedin_mcp.tools.jobs.search.tool import register as register_jobs_search
        from linkedin_mcp.tools.messaging.conversation.get.tool import (
            register as register_conversation_get,
        )
        from linkedin_mcp.tools.messaging.search.tool import register as register_messaging_search
        from linkedin_mcp.tools.messaging.send.tool import register as register_messaging_send
        from linkedin_mcp.tools.people.get.tool import register as register_people_get
        from linkedin_mcp.tools.people.search.tool import register as register_people_search
        from linkedin_mcp.tools.posts.comment.tool import register as register_posts_comment
        from linkedin_mcp.tools.posts.comments.list.tool import (
            register as register_posts_comments,
        )
        from linkedin_mcp.tools.posts.create.tool import register as register_posts_create
        from linkedin_mcp.tools.posts.get.tool import register as register_posts_get
        from linkedin_mcp.tools.posts.react.tool import register as register_posts_react
        from linkedin_mcp.tools.posts.search.tool import register as register_posts_search
        from linkedin_mcp.tools.server.status.tool import register as register_server_status
        from linkedin_mcp.tools.session.status.tool import register as register_session_status

        mcp = self._mcp
        operations = self._operations
        cursors = self._cursors
        account_id = self._settings.account_id
        register_server_status(mcp, operations)
        register_session_status(mcp, self._settings, self._browser)
        register_jobs_search(mcp, operations, job_search, cursors, account_id)
        register_jobs_get(mcp, operations, job_detail)
        register_people_search(mcp, operations, people_search, cursors, account_id)
        register_people_get(mcp, operations, person_profile)
        register_companies_search(mcp, operations, company_search, cursors, account_id)
        register_companies_get(mcp, operations, company_profile)
        register_posts_search(mcp, operations, post_search, cursors, account_id)
        register_posts_get(mcp, operations, post_detail)
        register_posts_comments(mcp, operations, post_comments, cursors, account_id)
        register_posts_create(mcp, operations, post_publishing)
        register_posts_comment(mcp, operations, post_comment)
        register_posts_react(mcp, operations, post_reaction)
        register_invitations_list(mcp, operations, invitation_list, cursors, account_id)
        register_connections_list(mcp, operations, connections_list, cursors, account_id)
        register_connections_search(mcp, operations, connections_search, cursors, account_id)
        register_send(mcp, operations, invitation_send)
        register_accept(mcp, operations, invitation_accept)
        register_ignore(mcp, operations, invitation_ignore)
        register_messaging_search(mcp, operations, conversation_search, cursors, account_id)
        register_conversation_get(mcp, operations, conversation_read)
        register_messaging_send(mcp, operations, message_send)
