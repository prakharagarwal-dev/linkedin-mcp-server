"""Shared contracts for one-shot LinkedIn account-changing actions."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from linkedin_mcp.linkedin.common import (
    AssetReference,
    ConversationId,
    Identifier,
    PostReference,
    ProfileSlug,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.linkedin.messaging.models import MessageGifInput
from linkedin_mcp.linkedin.posts.models import (
    CommentAttachment,
    EventPostContent,
    ExpertRequestPostContent,
    HiringPostContent,
    PostAudience,
    PostCollaboratorInput,
    PostCommentControl,
    PostCreateContent,
    PostGroupTarget,
    PostMentionInput,
    ReactionState,
)


class ActionType(StrEnum):
    INVITATION_SEND = "invitation_send"
    INVITATION_ACCEPT = "invitation_accept"
    INVITATION_IGNORE = "invitation_ignore"
    MESSAGE_SEND = "message_send"
    POST_CREATE = "post_create"
    COMMENT_CREATE = "comment_create"
    REACTION_SET = "reaction_set"


class ActionOutcome(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class ActionTarget(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    invitation_ref: Identifier | None = None
    conversation_id: ConversationId | None = None
    actor_profile_slug: ProfileSlug | None = None
    actor_profile_url: HttpUrl | None = None
    actor_display_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    post_ref: PostReference | None = None
    post_url: HttpUrl | None = None
    content_author_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    content_author_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_actor_and_content_target(self) -> ActionTarget:
        actor_values = (
            self.actor_profile_slug,
            self.actor_profile_url,
            self.actor_display_name,
        )
        if any(value is not None for value in actor_values) and not all(
            value is not None for value in actor_values
        ):
            raise ValueError("An action actor requires slug, URL, and display name")
        return self


class InvitationSendPayload(StrictModel):
    action_type: Literal[ActionType.INVITATION_SEND] = ActionType.INVITATION_SEND
    note: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class InvitationAcceptPayload(StrictModel):
    action_type: Literal[ActionType.INVITATION_ACCEPT] = ActionType.INVITATION_ACCEPT
    invitation_ref: Identifier


class InvitationIgnorePayload(StrictModel):
    action_type: Literal[ActionType.INVITATION_IGNORE] = ActionType.INVITATION_IGNORE
    invitation_ref: Identifier


class MessageSendPayload(StrictModel):
    action_type: Literal[ActionType.MESSAGE_SEND] = ActionType.MESSAGE_SEND
    message: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    attachment_refs: Annotated[tuple[AssetReference, ...], Field(max_length=20)] = ()
    gif: MessageGifInput | None = None
    reply_to_message_ref: (
        Annotated[
            str,
            StringConstraints(pattern=r"^message:[0-9a-f]{24}$"),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_message_content(self) -> MessageSendPayload:
        if self.message is None and not self.attachment_refs and self.gif is None:
            raise ValueError("A message payload requires text, attachments, or a GIF")
        if self.gif is not None and (self.message is not None or self.attachment_refs):
            raise ValueError("A GIF immediate-send payload cannot include text or file attachments")
        if len(set(self.attachment_refs)) != len(self.attachment_refs):
            raise ValueError("Message attachment references must be unique")
        return self


class PostCreatePayload(StrictModel):
    action_type: Literal[ActionType.POST_CREATE] = ActionType.POST_CREATE
    content: PostCreateContent
    audience: PostAudience
    group_target: PostGroupTarget | None = None
    comment_control: PostCommentControl
    brand_partnership: bool = False
    collaborators: Annotated[tuple[PostCollaboratorInput, ...], Field(max_length=5)] = ()
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_post_payload(self) -> PostCreatePayload:
        if self.scheduled_at is not None and self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        if (self.audience is PostAudience.GROUP) != (self.group_target is not None):
            raise ValueError("Group audience requires exactly one group_target")
        if self.brand_partnership and self.audience is not PostAudience.ANYONE:
            raise ValueError("Brand partnership posts must use the Anyone audience")
        if self.collaborators and self.audience is not PostAudience.ANYONE:
            raise ValueError("Collaborative posts must use the Anyone audience")
        if self.scheduled_at is not None and isinstance(
            self.content,
            EventPostContent | HiringPostContent | ExpertRequestPostContent,
        ):
            raise ValueError("LinkedIn does not schedule event, hiring, or expert-request posts")
        return self


class CommentCreatePayload(StrictModel):
    action_type: Literal[ActionType.COMMENT_CREATE] = ActionType.COMMENT_CREATE
    post_ref: PostReference
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()
    attachment: CommentAttachment | None = None

    @model_validator(mode="after")
    def validate_comment_payload(self) -> CommentCreatePayload:
        if self.text is None and self.attachment is None:
            raise ValueError("A comment payload requires text, a photo, or a GIF")
        return self


class ReactionSetPayload(StrictModel):
    action_type: Literal[ActionType.REACTION_SET] = ActionType.REACTION_SET
    post_ref: PostReference
    existing_reaction: ReactionState
    desired_reaction: ReactionState


ActionPayload = Annotated[
    InvitationSendPayload
    | InvitationAcceptPayload
    | InvitationIgnorePayload
    | MessageSendPayload
    | PostCreatePayload
    | CommentCreatePayload
    | ReactionSetPayload,
    Field(discriminator="action_type"),
]


class ActionCommand(StrictModel):
    """Resolved action data used only during one queued tool invocation."""

    action_type: ActionType
    target: ActionTarget
    payload: ActionPayload

    @model_validator(mode="after")
    def payload_matches_action_type(self) -> ActionCommand:
        if self.payload.action_type is not self.action_type:
            raise ValueError("Action payload type does not match action_type")
        return self


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
    action_type: ActionType
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
