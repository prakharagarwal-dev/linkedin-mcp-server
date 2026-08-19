"""Models owned by `linkedin.posts.react`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints


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


PostReference = Annotated[
    str, StringConstraints(pattern="^(?:activity|share|ugc-post):[0-9]{5,30}$")
]


class ReactionState(StrEnum):
    NONE = "none"
    LIKE = "like"
    CELEBRATE = "celebrate"
    SUPPORT = "support"
    LOVE = "love"
    INSIGHTFUL = "insightful"
    FUNNY = "funny"


class PostReactionInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    desired_reaction: ReactionState


class ActionType(StrEnum):
    REACTION_SET = "reaction_set"


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


class ReactionSetPayload(StrictModel):
    action_type: Literal[ActionType.REACTION_SET] = ActionType.REACTION_SET
    post_ref: PostReference
    existing_reaction: ReactionState
    desired_reaction: ReactionState


class ActionCommand(StrictModel):
    action_type: Literal[ActionType.REACTION_SET] = ActionType.REACTION_SET
    target: ActionTarget
    payload: ReactionSetPayload


class ActionInspection(StrictModel):
    target: ActionTarget
    current_state: Annotated[str, Field(min_length=1, max_length=200)]
    source_url: HttpUrl
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime
    existing_reaction: ReactionState | None = None


class ActionPageResult(StrictModel):
    outcome: ActionOutcome
    performed: bool | None
    final_state: Annotated[str, Field(min_length=1, max_length=200)]
    detail: Annotated[str, Field(min_length=1, max_length=1_000)]
    source_url: HttpUrl
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class ActionResult(StrictModel):
    action_type: Literal[ActionType.REACTION_SET] = ActionType.REACTION_SET
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
