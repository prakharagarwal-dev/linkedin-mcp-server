"""Models owned by `linkedin.invitations.send`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

PROFILE_SLUG_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{2,199}"


PROFILE_SLUG_PATTERN = rf"^{PROFILE_SLUG_SEGMENT_PATTERN}$"


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


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


class ActionType(StrEnum):
    INVITATION_SEND = "invitation_send"


class ActionOutcome(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class SourceType(StrEnum):
    ACTION_EXECUTION = "linkedin_action_execution"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class ActionTarget(StrictModel):
    profile_slug: str
    profile_url: HttpUrl
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    invitation_ref: Identifier | None = None
    conversation_id: str | None = None
    actor_profile_slug: str | None = None
    actor_profile_url: HttpUrl | None = None
    actor_display_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    post_ref: str | None = None
    post_url: HttpUrl | None = None
    content_author_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    content_author_url: HttpUrl | None = None


class InvitationSendPayload(StrictModel):
    action_type: Literal[ActionType.INVITATION_SEND] = ActionType.INVITATION_SEND
    note: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class ActionCommand(StrictModel):
    action_type: Literal[ActionType.INVITATION_SEND] = ActionType.INVITATION_SEND
    target: ActionTarget
    payload: InvitationSendPayload


class ActionInspection(StrictModel):
    target: ActionTarget
    current_state: Annotated[str, Field(min_length=1, max_length=200)]
    source_url: HttpUrl
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class ActionPageResult(StrictModel):
    outcome: ActionOutcome
    performed: bool | None
    final_state: Annotated[str, Field(min_length=1, max_length=200)]
    detail: Annotated[str, Field(min_length=1, max_length=1_000)]
    source_url: HttpUrl
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class ActionResult(StrictModel):
    action_type: Literal[ActionType.INVITATION_SEND] = ActionType.INVITATION_SEND
    outcome: ActionOutcome
    performed: bool | None
    final_state: Annotated[str, Field(min_length=1, max_length=200)]
    detail: Annotated[str, Field(min_length=1, max_length=1_000)]
    started_at: datetime
    completed_at: datetime


class ActionOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    result: ActionResult
    sources: tuple[SourceReference, ...]
