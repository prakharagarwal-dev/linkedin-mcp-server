"""Models owned by `linkedin.invitations.list`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


PaginationCursor = Annotated[
    str, StringConstraints(min_length=32, max_length=128, pattern="^[A-Za-z0-9_-]+$")
]


class PaginatedInput(StrictModel):
    """Shared public cursor contract for bounded collection capabilities."""

    page_size: Annotated[
        int, Field(ge=1, le=100, description="Maximum unique items returned in this page.")
    ] = 25
    cursor: (
        Annotated[
            PaginationCursor,
            Field(
                description=(
                    "Opaque continuation cursor from the immediately preceding page. "
                    "Cursors are process-local, single-use, filter-bound, and expiring."
                )
            ),
        ]
        | None
    ) = None


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


class SourceType(StrEnum):
    INVITATIONS = "linkedin_invitations"


class StopReason(StrEnum):
    RESULT_LIMIT = "result_limit"
    SAFETY_BOUND = "safety_bound"
    NO_NEW_RESULTS = "no_new_results"
    VISIBLE_PAGE_COMPLETE = "visible_page_complete"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class PaginationMetadata(StrictModel):
    """Reader-facing state for one page of a process-local live scan."""

    scan_id: Identifier
    page_size: Annotated[int, Field(ge=1, le=100)]
    returned_count: Annotated[int, Field(ge=0, le=100)]
    cumulative_count: Annotated[int, Field(ge=0)]
    has_more: bool
    next_cursor: PaginationCursor | None = None
    cursor_expires_at: datetime | None = None
    truncated: bool = False
    consistency: Literal["live_deduplicated"] = "live_deduplicated"

    @model_validator(mode="after")
    def validate_cursor_state(self) -> PaginationMetadata:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match the presence of next_cursor")
        if self.has_more != (self.cursor_expires_at is not None):
            raise ValueError("has_more must match the cursor expiry")
        if self.returned_count > self.page_size:
            raise ValueError("returned_count cannot exceed page_size")
        return self


class InvitationAvailableAction(StrEnum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    WITHDRAW = "withdraw"
    MESSAGE = "message"
    REPLY = "reply"


class InvitationDirection(StrEnum):
    RECEIVED = "received"
    SENT = "sent"


class InvitationEntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    SCHOOL = "school"
    GROUP = "group"
    EVENT = "event"
    NEWSLETTER = "newsletter"
    OTHER = "other"


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


class InvitationType(StrEnum):
    CONNECTION_REQUEST = "connection_request"
    COMPANY_FOLLOW = "company_follow"
    SCHOOL_INVITATION = "school_invitation"
    GROUP_INVITATION = "group_invitation"
    EVENT_INVITATION = "event_invitation"
    NEWSLETTER_INVITATION = "newsletter_invitation"
    OTHER = "other"


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
