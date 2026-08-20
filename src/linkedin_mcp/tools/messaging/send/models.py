"""Models owned by `linkedin.messaging.send`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

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


AssetReference = Annotated[str, StringConstraints(min_length=1)]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


ConversationId = Annotated[
    str, StringConstraints(min_length=3, max_length=500, pattern="^[A-Za-z0-9_%=-]+$")
]


class ConversationTargetInput(StrictModel):
    profile_slug: ProfileSlug | None = None
    conversation_id: ConversationId | None = None
    conversation_ref: (
        Annotated[str, StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$")] | None
    ) = None

    @model_validator(mode="after")
    def require_one_target(self) -> ConversationTargetInput:
        targets = (self.profile_slug, self.conversation_id, self.conversation_ref)
        if sum(value is not None for value in targets) != 1:
            raise ValueError(
                "Exactly one of profile_slug, conversation_id, or conversation_ref is required"
            )
        return self


class MessageFileInput(StrictModel):
    asset_ref: AssetReference


class MessageGifInput(StrictModel):
    search_query: Annotated[str, Field(min_length=1, max_length=200)]
    result_title: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description=(
                "Exact title exposed inside the current KLIPY result image alternative text."
            ),
        ),
    ]


class MessageSendInput(ConversationTargetInput):
    context_id: Identifier
    request_id: Identifier
    message: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=8_000,
                description="Exact message text; emoji characters are retained verbatim.",
            ),
        ]
        | None
    ) = None
    attachments: Annotated[tuple[MessageFileInput, ...], Field(max_length=20)] = ()
    gif: MessageGifInput | None = None
    reply_to_message_ref: (
        Annotated[
            str,
            StringConstraints(pattern=r"^message:[0-9a-f]{24}$"),
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "Optional exact message_ref from conversation.get. LinkedIn's visible reply "
            "control is bound to this message before the requested content is sent."
        ),
    )

    @model_validator(mode="after")
    def validate_message_content(self) -> MessageSendInput:
        if self.message is None and not self.attachments and self.gif is None:
            raise ValueError("A message requires text, one or more attachments, or a GIF")
        if self.gif is not None and (self.message is not None or self.attachments):
            raise ValueError(
                "A GIF is an immediate-send LinkedIn action and cannot be combined "
                "with text or file attachments"
            )
        refs = tuple(attachment.asset_ref for attachment in self.attachments)
        if len(set(refs)) != len(refs):
            raise ValueError("Message attachment references must be unique")
        return self


class ActionType(StrEnum):
    MESSAGE_SEND = "message_send"


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


class MessageSendPayload(StrictModel):
    action_type: Literal[ActionType.MESSAGE_SEND] = ActionType.MESSAGE_SEND
    message: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    attachment_refs: Annotated[tuple[AssetReference, ...], Field(max_length=20)] = ()
    gif: MessageGifInput | None = None
    reply_to_message_ref: (
        Annotated[str, StringConstraints(pattern=r"^message:[0-9a-f]{24}$")] | None
    ) = None

    @model_validator(mode="after")
    def validate_payload(self) -> MessageSendPayload:
        if self.message is None and not self.attachment_refs and self.gif is None:
            raise ValueError("A message payload requires text, attachments, or a GIF")
        if self.gif is not None and (self.message is not None or self.attachment_refs):
            raise ValueError("A GIF immediate-send payload cannot include text or file attachments")
        if len(set(self.attachment_refs)) != len(self.attachment_refs):
            raise ValueError("Message attachment references must be unique")
        return self


class ActionCommand(StrictModel):
    action_type: Literal[ActionType.MESSAGE_SEND] = ActionType.MESSAGE_SEND
    target: ActionTarget
    payload: MessageSendPayload


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
    action_type: Literal[ActionType.MESSAGE_SEND] = ActionType.MESSAGE_SEND
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
