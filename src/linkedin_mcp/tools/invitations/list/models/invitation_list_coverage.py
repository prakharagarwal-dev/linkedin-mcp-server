"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import StopReason, StrictModel
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_entity_type import InvitationEntityType
from linkedin_mcp.tools.invitations.list.models.invitation_filter import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    InvitationFilter,
)
from linkedin_mcp.tools.invitations.list.models.invitation_type import InvitationType


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
