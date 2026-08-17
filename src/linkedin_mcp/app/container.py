"""Composition root for the standalone server process."""

from __future__ import annotations

from dataclasses import dataclass, field

from linkedin_mcp import __version__
from linkedin_mcp.app import CapabilityWorker, PaginationManager
from linkedin_mcp.app.assets import LocalAssetStore
from linkedin_mcp.app.executor import CapabilityExecutor
from linkedin_mcp.config import Settings, runtime_configuration_fingerprint
from linkedin_mcp.mcp.context import ClientSessionRegistry
from linkedin_mcp.runtime import AccountProcessLock
from linkedin_mcp.tools._shared.browser import BrowserManager
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


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    browser: BrowserManager
    executor: CapabilityExecutor
    worker: CapabilityWorker
    process_lock: AccountProcessLock
    clients: ClientSessionRegistry = field(default_factory=ClientSessionRegistry)
    _started: bool = field(default=False, init=False)

    async def start(self) -> None:
        if self._started:
            return
        self.process_lock.acquire()
        try:
            await self.worker.start()
            self.browser.start_session_bootstrap()
        except BaseException:
            self.process_lock.release()
            raise
        self._started = True

    async def close(self) -> None:
        try:
            if self._started:
                await self.worker.quiesce()
        finally:
            self._started = False
            try:
                await self.worker.close()
            finally:
                try:
                    await self.executor.close()
                finally:
                    try:
                        await self.browser.close()
                    finally:
                        self.process_lock.release()

    async def quiesce(self) -> None:
        """Stop accepting queued calls and let the active call reach a terminal result."""

        if self._started:
            await self.worker.quiesce()


def create_production_container(settings: Settings) -> AppContainer:
    browser = BrowserManager(settings)
    connections_list = ConnectionsListPage(
        browser,
        max_scroll_rounds=settings.connections_max_scroll_rounds_per_call,
    )
    invitation_list = InvitationListPage(
        browser,
        max_scroll_rounds=settings.invitations_max_scroll_rounds_per_call,
    )
    asset_store = LocalAssetStore(settings.asset_root_path)
    conversation_search = ConversationSearchPage(
        browser,
        max_scroll_rounds=settings.messaging_max_scroll_rounds_per_call,
    )
    pagination = PaginationManager(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )
    executor = CapabilityExecutor(
        settings=settings,
        job_search=JobSearchPage(
            browser,
            max_pages=settings.job_search_max_pages_per_call,
        ),
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
        post_search=PostSearchPage(
            browser,
            max_pages=settings.post_search_max_pages_per_call,
        ),
        post_detail=PostDetailPage(browser),
        post_comments=PostCommentsPage(
            browser,
            max_expansion_rounds=settings.post_comments_max_expansion_rounds_per_call,
        ),
        post_publishing=PostPublishingPage(
            browser,
            asset_store,
        ),
        post_comment=PostCommentPage(
            browser,
            asset_store,
        ),
        post_reaction=PostReactionPage(
            browser,
            asset_store,
        ),
        invitation_list=invitation_list,
        connections_list=connections_list,
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
            asset_store,
            conversation_search=conversation_search,
            max_history_rounds=settings.messaging_max_scroll_rounds_per_call,
        ),
        pagination=pagination,
    )
    worker = CapabilityWorker(
        executor,
        queue_capacity=settings.queue_capacity,
        pagination=pagination,
        account_id=settings.account_id,
    )
    return AppContainer(
        settings=settings,
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(
            settings.runtime_lock_path,
            account_id=settings.account_id,
            command="serve",
            transport=settings.transport,
            version=__version__,
            configuration_fingerprint=runtime_configuration_fingerprint(settings),
        ),
    )
