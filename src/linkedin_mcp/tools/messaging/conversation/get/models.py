"""Models owned by `linkedin.messaging.conversation.get`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

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


ConversationId = Annotated[
    str, StringConstraints(min_length=3, max_length=500, pattern="^[A-Za-z0-9_%=-]+$")
]


class SourceType(StrEnum):
    MESSAGING_CONVERSATION = "linkedin_messaging_conversation"


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


class ConversationCoverage(StrictModel):
    messages_observed: Annotated[int, Field(ge=0)]
    messages_returned: Annotated[int, Field(ge=0)]
    attachments_returned: Annotated[int, Field(ge=0)] = 0
    replies_returned: Annotated[int, Field(ge=0)] = 0
    reactions_returned: Annotated[int, Field(ge=0)] = 0
    max_messages: Annotated[int, Field(ge=1)]
    rounds_visited: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    history_complete: bool
    truncated: bool
    captured_at: datetime


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


class ConversationGetInput(ConversationTargetInput):
    context_id: Identifier
    request_id: Identifier
    max_messages: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description=(
                "Maximum latest messages returned after bounded traversal of LinkedIn's "
                "reverse-virtualized visible history."
            ),
        ),
    ] = 50


class MessageAttachmentKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"


class MessageAttachmentObservation(StrictModel):
    kind: MessageAttachmentKind
    name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    accessible_label: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    resource_url: HttpUrl | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> MessageAttachmentObservation:
        if self.name is None and self.accessible_label is None and self.resource_url is None:
            raise ValueError("A message attachment requires visible identity evidence")
        return self


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    SYSTEM = "system"


class MessageObservation(StrictModel):
    message_ref: Identifier
    direction: MessageDirection
    sender_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    sent_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    attachments: Annotated[
        tuple[MessageAttachmentObservation, ...],
        Field(max_length=20),
    ] = ()
    edited: bool = False
    reply_to_sender_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    reply_to_text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    reaction_summaries: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=500)], ...],
        Field(max_length=20),
    ] = ()
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_message_content(self) -> MessageObservation:
        if self.text is None and not self.attachments:
            raise ValueError("A message observation requires text or a visible attachment")
        return self


class ConversationObservation(StrictModel):
    conversation_ref: (
        Annotated[str, StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$")] | None
    ) = None
    conversation_id: ConversationId | None = None
    participant_profile_slug: ProfileSlug | None = None
    participant_profile_url: HttpUrl | None = None
    participant_name: Annotated[str, Field(min_length=1, max_length=500)]
    is_group: bool = False
    messages: tuple[MessageObservation, ...]
    visible_text: Annotated[str, Field(min_length=1)]
    coverage: ConversationCoverage
    captured_at: datetime


class ConversationGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    conversation: ConversationObservation
    sources: tuple[SourceReference, ...]
