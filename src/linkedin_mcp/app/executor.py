"""Compose capability-owned operations for worker execution."""

from __future__ import annotations

from linkedin_mcp.app.pagination import PaginationManager
from linkedin_mcp.config import Settings
from linkedin_mcp.tools.companies.get.operation import (
    CompanyProfileProvider,
    GetCompanyOperation,
)
from linkedin_mcp.tools.companies.search.operation import (
    CompanySearchProvider,
    SearchCompaniesOperation,
)
from linkedin_mcp.tools.connections.list.operation import (
    ConnectionsListProvider,
    ListConnectionsOperation,
)
from linkedin_mcp.tools.connections.search.operation import (
    ConnectionsSearchProvider,
    SearchConnectionsOperation,
)
from linkedin_mcp.tools.invitations.accept.operation import (
    AcceptInvitationOperation,
    InvitationAcceptProvider,
)
from linkedin_mcp.tools.invitations.ignore.operation import (
    IgnoreInvitationOperation,
    InvitationIgnoreProvider,
)
from linkedin_mcp.tools.invitations.list.operation import (
    InvitationListProvider,
    ListInvitationsOperation,
    ProgressReporter,
)
from linkedin_mcp.tools.invitations.send.operation import (
    InvitationSendProvider,
    SendInvitationOperation,
)
from linkedin_mcp.tools.jobs.get.operation import GetJobOperation, JobDetailProvider
from linkedin_mcp.tools.jobs.search.operation import JobSearchProvider, SearchJobsOperation
from linkedin_mcp.tools.messaging.conversation.get.operation import (
    ConversationReadProvider,
    GetConversationOperation,
)
from linkedin_mcp.tools.messaging.search.operation import (
    ConversationSearchProvider,
    SearchMessagesOperation,
)
from linkedin_mcp.tools.messaging.send.operation import MessageSendProvider, SendMessageOperation
from linkedin_mcp.tools.people.get.operation import GetPersonOperation, PersonProfileProvider
from linkedin_mcp.tools.people.search.operation import PeopleSearchProvider, SearchPeopleOperation
from linkedin_mcp.tools.posts.comment.operation import CommentPostOperation, PostCommentProvider
from linkedin_mcp.tools.posts.comments.list.operation import (
    ListPostCommentsOperation,
    PostCommentsProvider,
)
from linkedin_mcp.tools.posts.create.operation import CreatePostOperation, PostPublishingProvider
from linkedin_mcp.tools.posts.get.operation import GetPostOperation, PostDetailProvider
from linkedin_mcp.tools.posts.react.operation import PostReactionProvider, ReactPostOperation
from linkedin_mcp.tools.posts.search.operation import PostSearchProvider, SearchPostsOperation


class CapabilityExecutor(
    SearchJobsOperation,
    GetJobOperation,
    SearchPeopleOperation,
    GetPersonOperation,
    SearchCompaniesOperation,
    GetCompanyOperation,
    SearchPostsOperation,
    GetPostOperation,
    ListPostCommentsOperation,
    CreatePostOperation,
    CommentPostOperation,
    ReactPostOperation,
    ListConnectionsOperation,
    SearchConnectionsOperation,
    ListInvitationsOperation,
    SendInvitationOperation,
    AcceptInvitationOperation,
    IgnoreInvitationOperation,
    SearchMessagesOperation,
    GetConversationOperation,
    SendMessageOperation,
):
    """Compose capability-owned operations into the single browser worker runner."""

    def __init__(
        self,
        *,
        settings: Settings,
        job_search: JobSearchProvider,
        job_detail: JobDetailProvider,
        people_search: PeopleSearchProvider,
        connections_search: ConnectionsSearchProvider,
        person_profile: PersonProfileProvider,
        company_search: CompanySearchProvider,
        company_profile: CompanyProfileProvider,
        post_search: PostSearchProvider,
        post_detail: PostDetailProvider,
        post_comments: PostCommentsProvider,
        post_publishing: PostPublishingProvider,
        post_comment: PostCommentProvider,
        post_reaction: PostReactionProvider,
        invitation_list: InvitationListProvider,
        connections_list: ConnectionsListProvider,
        invitation_send: InvitationSendProvider,
        invitation_accept: InvitationAcceptProvider,
        invitation_ignore: InvitationIgnoreProvider,
        conversation_search: ConversationSearchProvider,
        conversation_read: ConversationReadProvider,
        message_send: MessageSendProvider,
        pagination: PaginationManager | None = None,
    ) -> None:
        self._settings = settings
        self._job_search = job_search
        self._job_detail = job_detail
        self._people_search = people_search
        self._connections_search = connections_search
        self._person_profile = person_profile
        self._company_search = company_search
        self._company_profile = company_profile
        self._post_search = post_search
        self._post_detail = post_detail
        self._post_comments = post_comments
        self._post_publishing = post_publishing
        self._post_comment = post_comment
        self._post_reaction = post_reaction
        self._invitation_list = invitation_list
        self._connections_list = connections_list
        self._invitation_send = invitation_send
        self._invitation_accept = invitation_accept
        self._invitation_ignore = invitation_ignore
        self._conversation_search = conversation_search
        self._conversation_read = conversation_read
        self._message_send = message_send
        self._pagination = pagination or PaginationManager(
            ttl_seconds=settings.pagination_cursor_ttl_seconds,
            max_active_cursors=settings.pagination_max_active_cursors,
            max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
        )

    async def close(self) -> None:
        await self._pagination.close()


__all__ = [
    "CapabilityExecutor",
    "CompanyProfileProvider",
    "CompanySearchProvider",
    "ConnectionsListProvider",
    "ConnectionsSearchProvider",
    "ConversationReadProvider",
    "ConversationSearchProvider",
    "InvitationAcceptProvider",
    "InvitationIgnoreProvider",
    "InvitationListProvider",
    "InvitationSendProvider",
    "JobDetailProvider",
    "JobSearchProvider",
    "MessageSendProvider",
    "PeopleSearchProvider",
    "PersonProfileProvider",
    "PostCommentProvider",
    "PostCommentsProvider",
    "PostDetailProvider",
    "PostPublishingProvider",
    "PostReactionProvider",
    "PostSearchProvider",
    "ProgressReporter",
]
