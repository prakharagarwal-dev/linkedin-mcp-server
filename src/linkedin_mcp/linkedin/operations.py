"""Composition facade for feature-owned LinkedIn operations."""

from __future__ import annotations

from linkedin_mcp.app.pagination import PaginationManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.linkedin.companies.operations import (
    CompaniesOperations,
    CompanyProfileProvider,
    CompanySearchProvider,
)
from linkedin_mcp.linkedin.jobs.operations import (
    JobDetailProvider,
    JobSearchProvider,
    JobsOperations,
)
from linkedin_mcp.linkedin.messaging.operations import (
    ConversationProvider,
    ConversationSearchProvider,
    MessagingOperations,
)
from linkedin_mcp.linkedin.network.operations import (
    ConnectionsListProvider,
    InvitationActionProvider,
    InvitationListProvider,
    NetworkOperations,
    ProgressReporter,
)
from linkedin_mcp.linkedin.people.operations import (
    PeopleOperations,
    PeopleSearchProvider,
    PersonProfileProvider,
)
from linkedin_mcp.linkedin.posts.operations import (
    PostCommentsProvider,
    PostDetailProvider,
    PostEngagementProvider,
    PostPublishingProvider,
    PostSearchProvider,
    PostsOperations,
)


class CapabilityExecutor(
    JobsOperations,
    PeopleOperations,
    CompaniesOperations,
    PostsOperations,
    NetworkOperations,
    MessagingOperations,
):
    """Expose one stable executor while each feature owns its operation methods."""

    def __init__(
        self,
        *,
        settings: Settings,
        job_search: JobSearchProvider,
        job_detail: JobDetailProvider,
        people_search: PeopleSearchProvider,
        person_profile: PersonProfileProvider,
        company_search: CompanySearchProvider,
        company_profile: CompanyProfileProvider,
        post_search: PostSearchProvider,
        post_detail: PostDetailProvider,
        post_comments: PostCommentsProvider,
        post_publishing: PostPublishingProvider,
        post_engagement: PostEngagementProvider,
        invitation_list: InvitationListProvider,
        connections_list: ConnectionsListProvider,
        invitation_actions: InvitationActionProvider,
        conversation_search: ConversationSearchProvider,
        conversation: ConversationProvider,
        pagination: PaginationManager | None = None,
    ) -> None:
        self._settings = settings
        self._job_search = job_search
        self._job_detail = job_detail
        self._people_search = people_search
        self._person_profile = person_profile
        self._company_search = company_search
        self._company_profile = company_profile
        self._post_search = post_search
        self._post_detail = post_detail
        self._post_comments = post_comments
        self._post_publishing = post_publishing
        self._post_engagement = post_engagement
        self._invitation_list = invitation_list
        self._connections_list = connections_list
        self._invitation_actions = invitation_actions
        self._conversation_search = conversation_search
        self._conversation = conversation
        self._pagination = pagination or PaginationManager(
            ttl_seconds=settings.pagination_cursor_ttl_seconds,
            max_active_cursors=settings.pagination_max_active_cursors,
            max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
        )

    async def close(self) -> None:
        await self._pagination.close()


def safe_capability_error(error: Exception) -> LinkedInMCPError:
    if isinstance(error, LinkedInMCPError):
        return error
    return InternalServerError()


__all__ = [
    "CapabilityExecutor",
    "CompanyProfileProvider",
    "CompanySearchProvider",
    "ConnectionsListProvider",
    "ConversationProvider",
    "ConversationSearchProvider",
    "InvitationActionProvider",
    "InvitationListProvider",
    "JobDetailProvider",
    "JobSearchProvider",
    "PeopleSearchProvider",
    "PersonProfileProvider",
    "PostCommentsProvider",
    "PostDetailProvider",
    "PostEngagementProvider",
    "PostPublishingProvider",
    "PostSearchProvider",
    "ProgressReporter",
    "safe_capability_error",
]
