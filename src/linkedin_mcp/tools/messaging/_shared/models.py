from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
    ConversationId,
    Identifier,
    PaginatedInput,
    PaginationMetadata,
    ProfileSlug,
    SourceReference,
    StopReason,
    StrictModel,
)


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    SYSTEM = "system"


class ConversationCategory(StrEnum):
    FOCUSED = "focused"
    OTHER = "other"
    ARCHIVED = "archived"
    SPAM = "spam"


class ConversationFilter(StrEnum):
    JOBS = "jobs"
    UNREAD = "unread"
    CONNECTIONS = "connections"
    STARRED = "starred"
    INMAIL = "inmail"


class MessageAttachmentKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"


class ConversationSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description=(
                    "LinkedIn's visible Search messages value. The same field searches "
                    "recipient names and message keywords."
                ),
            ),
        ]
        | None
    ) = None
    category: ConversationCategory | None = Field(
        default=None,
        description=(
            "Optional current desktop inbox category. When omitted, LinkedIn's Focused "
            "category is selected deterministically."
        ),
    )
    filter: ConversationFilter | None = Field(
        default=None,
        description=(
            "Optional current desktop message filter. LinkedIn exposes these as mutually "
            "exclusive pills, so exactly zero or one filter can be selected."
        ),
    )

    @model_validator(mode="after")
    def require_search_criterion(self) -> ConversationSearchInput:
        if self.query is None and self.category is None and self.filter is None:
            raise ValueError(
                "Message search requires query, category, or one visible message filter"
            )
        return self

    @property
    def resolved_category(self) -> ConversationCategory:
        return self.category or ConversationCategory.FOCUSED


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


class ConversationSummary(StrictModel):
    conversation_ref: Annotated[
        str,
        StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$"),
    ]
    conversation_id: ConversationId | None = None
    participant_profile_slug: ProfileSlug | None = None
    participant_profile_url: HttpUrl | None = None
    participant_name: Annotated[str, Field(min_length=1, max_length=500)]
    is_group: bool = False
    last_message_text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    last_activity_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    unread: bool
    starred: bool = False
    muted: bool = False
    labels: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=200)], ...],
        Field(max_length=10),
    ] = ()
    visible_text: Annotated[str, Field(min_length=1)]


class ConversationSearchCoverage(StrictModel):
    query: str | None
    category: ConversationCategory
    filter: ConversationFilter | None = None
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class ConversationSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    conversations: tuple[ConversationSummary, ...]
    coverage: ConversationSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


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
