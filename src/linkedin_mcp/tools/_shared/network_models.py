from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
    PaginationMetadata,
    ProfileSlug,
    SourceReference,
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.people.search.models.people_search_connection_degree import (
    PeopleSearchConnectionDegree,
)
from linkedin_mcp.tools.people.search.models.people_search_filter_base import PeopleSearchFilterBase
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters
from linkedin_mcp.tools.people.search.models.people_search_input import PeopleSearchInput
from linkedin_mcp.tools.people.search.models.people_search_output import PeopleSearchOutput


class InvitationDirection(StrEnum):
    RECEIVED = "received"
    SENT = "sent"


class InvitationFilter(StrEnum):
    ALL = "all"
    FOCUSED = "focused"
    OTHER = "other"
    VERIFIED = "verified"
    SAME_COMPANY = "same_company"
    SAME_SCHOOL = "same_school"
    MUTUAL_CONNECTIONS = "mutual_connections"
    PEOPLE = "people"


CURRENT_RECEIVED_INVITATION_VIEWS: tuple[InvitationFilter, ...] = (
    InvitationFilter.FOCUSED,
    InvitationFilter.OTHER,
    InvitationFilter.VERIFIED,
    InvitationFilter.MUTUAL_CONNECTIONS,
    InvitationFilter.SAME_COMPANY,
    InvitationFilter.SAME_SCHOOL,
)


class InvitationEntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    SCHOOL = "school"
    GROUP = "group"
    EVENT = "event"
    NEWSLETTER = "newsletter"
    OTHER = "other"


class InvitationType(StrEnum):
    CONNECTION_REQUEST = "connection_request"
    COMPANY_FOLLOW = "company_follow"
    SCHOOL_INVITATION = "school_invitation"
    GROUP_INVITATION = "group_invitation"
    EVENT_INVITATION = "event_invitation"
    NEWSLETTER_INVITATION = "newsletter_invitation"
    OTHER = "other"


class InvitationAvailableAction(StrEnum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    WITHDRAW = "withdraw"
    MESSAGE = "message"
    REPLY = "reply"


class ConnectionsSortBy(StrEnum):
    RECENTLY_ADDED = "recently_added"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"


class ConnectionsSearchFilters(PeopleSearchFilterBase):
    """People filters for established connections; first degree is server-enforced."""

    def as_people_search_filters(self) -> PeopleSearchFilters:
        return PeopleSearchFilters.model_validate(
            {
                **self.model_dump(mode="python"),
                "connection_degrees": (PeopleSearchConnectionDegree.FIRST,),
            }
        )


class InvitationListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    direction: InvitationDirection = InvitationDirection.RECEIVED
    invitation_filter: InvitationFilter | None = Field(
        default=None,
        description=(
            "Current visible LinkedIn invitation filter. Omit for the deduplicated union of "
            "every Received view or for Sent People."
        ),
    )

    @model_validator(mode="after")
    def validate_direction_filter(self) -> InvitationListInput:
        selected = self.resolved_filter
        if self.direction is InvitationDirection.SENT and selected is not InvitationFilter.PEOPLE:
            raise ValueError("Sent invitations support only the visible People filter")
        if self.direction is InvitationDirection.RECEIVED and selected is InvitationFilter.PEOPLE:
            raise ValueError("The People filter applies only to sent invitations")
        return self

    @property
    def resolved_filter(self) -> InvitationFilter:
        if self.invitation_filter is not None:
            return self.invitation_filter
        if self.direction is InvitationDirection.SENT:
            return InvitationFilter.PEOPLE
        return InvitationFilter.ALL


class ConnectionsListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED


class ConnectionsSearchInput(PaginatedInput):
    """Search established first-degree connections through LinkedIn People search."""

    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for connection search.",
            ),
        ]
        | None
    ) = None
    filters: ConnectionsSearchFilters = Field(
        default_factory=ConnectionsSearchFilters,
        description=(
            "Optional visible People filters. First-degree connection filtering is always "
            "enforced by the server and cannot be overridden."
        ),
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> ConnectionsSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Connection search requires query or at least one filter")
        return self

    def as_people_search_input(self) -> PeopleSearchInput:
        return PeopleSearchInput(
            context_id=self.context_id,
            request_id=self.request_id,
            query=self.query,
            filters=self.filters.as_people_search_filters(),
            page_size=self.page_size,
        )


class InvitationSendInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
    note: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Optional personalized invitation note. LinkedIn currently limits "
                    "personalized invitations to 200 characters."
                ),
            ),
        ]
        | None
    ) = None


class InvitationAcceptInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug


class InvitationIgnoreInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug


class InvitationEntity(StrictModel):
    entity_ref: Identifier
    entity_type: InvitationEntityType
    entity_url: HttpUrl | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    slug: (
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,199}$",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_known_entity_identity(self) -> InvitationEntity:
        if self.entity_type is not InvitationEntityType.OTHER and (
            self.entity_url is None or self.slug is None
        ):
            raise ValueError("Known invitation entities require a canonical URL and slug")
        return self


class InvitationEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    captured_at: datetime


class InvitationSummary(StrictModel):
    invitation_ref: Identifier
    direction: InvitationDirection
    invitation_type: InvitationType
    primary_entity: InvitationEntity
    inviter: InvitationEntity | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    context: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    sent_or_received_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    relationship_context: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    available_actions: tuple[InvitationAvailableAction, ...]
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[InvitationEvidence, ...]


class InvitationListCoverage(StrictModel):
    direction: InvitationDirection
    invitation_filter: InvitationFilter
    advertised_count: (
        Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "LinkedIn's exact count for one selected visible view. Null for the "
                    "server-defined Received all union or when LinkedIn omits an empty "
                    "view's count control and the collector independently proves that view "
                    "empty."
                ),
            ),
        ]
        | None
    )
    unique_count: Annotated[
        int,
        Field(
            ge=0,
            description="Stable invitation identities observed in this bounded live traversal.",
        ),
    ]
    view_counts: dict[InvitationFilter, Annotated[int, Field(ge=0)]]
    unadvertised_empty_views: tuple[InvitationFilter, ...] = Field(
        default=(),
        description=(
            "Selected views whose count control LinkedIn omitted and whose zero inventory "
            "was independently established from the current visible surface."
        ),
    )
    view_source_urls: dict[InvitationFilter, HttpUrl]
    view_membership_count: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "Sum of every reconciled selected-view count, including independently "
                "proved zero inventories whose count controls LinkedIn omitted."
            ),
        ),
    ]
    overlap_count: Annotated[
        int,
        Field(
            ge=0,
            description="Repeated view memberships observed and removed from the live union.",
        ),
    ]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    scroll_rounds: Annotated[int, Field(ge=0)]
    collection_attempts: Annotated[int, Field(ge=1, le=2)]
    neighboring_recommendation_count: Annotated[int, Field(ge=0)]
    invitation_type_counts: dict[InvitationType, Annotated[int, Field(ge=1)]]
    entity_type_counts: dict[InvitationEntityType, Annotated[int, Field(ge=1)]]
    stop_reason: StopReason
    captured_at: datetime

    @model_validator(mode="after")
    def validate_live_traversal(self) -> InvitationListCoverage:
        expected_views: set[InvitationFilter]
        if self.direction is InvitationDirection.SENT:
            expected_views = {InvitationFilter.PEOPLE}
        elif self.invitation_filter is InvitationFilter.ALL:
            expected_views = set(CURRENT_RECEIVED_INVITATION_VIEWS)
        else:
            expected_views = {self.invitation_filter}
        if set(self.view_counts) != expected_views:
            raise ValueError("Invitation coverage must identify every captured visible view")
        if set(self.view_source_urls) != expected_views:
            raise ValueError("Invitation coverage must identify every visible view source URL")
        omitted_empty_views = set(self.unadvertised_empty_views)
        if len(omitted_empty_views) != len(self.unadvertised_empty_views):
            raise ValueError("Unadvertised empty invitation views cannot contain duplicates")
        if not omitted_empty_views.issubset(expected_views):
            raise ValueError("Unadvertised empty invitation views must belong to this traversal")
        if any(self.view_counts.get(view) != 0 for view in omitted_empty_views):
            raise ValueError("An unadvertised invitation view must reconcile to zero")
        if sum(self.view_counts.values()) != self.view_membership_count:
            raise ValueError("Invitation view counts must equal the view-membership total")
        if self.invitation_filter is InvitationFilter.ALL:
            if self.advertised_count is not None:
                raise ValueError("Received All has no current LinkedIn advertised count")
        elif self.invitation_filter in omitted_empty_views:
            if self.advertised_count is not None or self.view_membership_count != 0:
                raise ValueError(
                    "An omitted empty invitation view cannot claim an advertised count"
                )
        elif (
            self.advertised_count != self.view_membership_count
            or self.view_counts.get(self.invitation_filter) != self.advertised_count
        ):
            raise ValueError("A single invitation view must preserve its advertised count")
        if self.unique_count + self.overlap_count > self.view_membership_count:
            raise ValueError("Observed invitation memberships exceed the advertised inventory")
        if sum(self.invitation_type_counts.values()) != self.unique_count:
            raise ValueError("Invitation type counts must equal the observed unique count")
        if sum(self.entity_type_counts.values()) != self.unique_count:
            raise ValueError("Invitation entity counts must equal the observed unique count")
        if self.result_count > self.unique_count or self.result_count > self.max_results:
            raise ValueError("Returned invitations exceed this bounded traversal")
        if self.stop_reason not in {
            StopReason.RESULT_LIMIT,
            StopReason.SAFETY_BOUND,
            StopReason.VISIBLE_PAGE_COMPLETE,
        }:
            raise ValueError("Invitation traversal has an unsupported stop reason")
        if self.stop_reason is StopReason.RESULT_LIMIT and self.unique_count < self.max_results:
            raise ValueError("Invitation result-limit coverage did not reach its traversal limit")
        if self.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE:
            if self.unique_count + self.overlap_count != self.view_membership_count:
                raise ValueError("Completed invitation traversal must reconcile view memberships")
            if self.invitation_filter is not InvitationFilter.ALL:
                if self.invitation_filter in omitted_empty_views:
                    if self.unique_count != 0 or self.overlap_count != 0:
                        raise ValueError("A completed omitted invitation view must remain empty")
                elif self.unique_count != self.advertised_count or self.overlap_count != 0:
                    raise ValueError(
                        "A completed single invitation view must reconcile its exact count"
                    )
        return self


class InvitationListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    invitations: tuple[InvitationSummary, ...]
    coverage: InvitationListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]

    @model_validator(mode="after")
    def validate_live_page(self) -> InvitationListOutput:
        returned = len(self.invitations)
        if self.coverage.result_count != returned or self.pagination.returned_count != returned:
            raise ValueError("Invitation page counts must match the returned invitations")
        if self.pagination.consistency != "live_deduplicated":
            raise ValueError("Invitation pagination must identify live-deduplicated consistency")
        if self.pagination.has_more and self.coverage.stop_reason not in {
            StopReason.RESULT_LIMIT,
            StopReason.SAFETY_BOUND,
        }:
            raise ValueError("Invitation continuation requires an honest non-terminal stop reason")
        if (
            not self.pagination.has_more
            and not self.pagination.truncated
            and self.coverage.stop_reason is not StopReason.VISIBLE_PAGE_COMPLETE
        ):
            raise ValueError("A complete invitation scan requires reconciled terminal coverage")
        references = [item.invitation_ref for item in self.invitations]
        if len(references) != len(set(references)):
            raise ValueError("Invitation pages cannot contain duplicate references")
        if any(item.direction is not self.coverage.direction for item in self.invitations):
            raise ValueError("Invitation page items must match the selected direction")
        return self


class ConnectionSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connected_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class ConnectionsListCoverage(StrictModel):
    sort_by: ConnectionsSortBy
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class ConnectionsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    connections: tuple[ConnectionSummary, ...]
    coverage: ConnectionsListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class ConnectionsSearchOutput(PeopleSearchOutput):
    """People-shaped results from LinkedIn's broad Connections search entry point."""
