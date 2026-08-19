"""Models owned by `linkedin.posts.comment`."""

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


PostReference = Annotated[
    str, StringConstraints(pattern="^(?:activity|share|ugc-post):[0-9]{5,30}$")
]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


CompanySlug = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"),
]


class PostMentionInput(StrictModel):
    token: Annotated[str, Field(min_length=2, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostMentionInput:
        if not self.token.startswith("@"):
            raise ValueError("A post mention token must begin with @")
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("A post mention requires exactly one member or company identity")
        return self


class CommentAttachmentType(StrEnum):
    PHOTO = "photo"
    GIF = "gif"


class CommentGifAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.GIF] = CommentAttachmentType.GIF
    search_query: Annotated[str, Field(min_length=1, max_length=200)]
    visible_result_label: Annotated[str, Field(min_length=1, max_length=500)]


class CommentPhotoAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.PHOTO] = CommentAttachmentType.PHOTO
    asset_ref: AssetReference


CommentAttachment = Annotated[
    CommentPhotoAttachment | CommentGifAttachment,
    Field(discriminator="attachment_type"),
]


class PostCommentInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()
    attachment: CommentAttachment | None = None

    @model_validator(mode="after")
    def validate_comment_content(self) -> PostCommentInput:
        if self.text is None and self.attachment is None:
            raise ValueError("A comment requires text, a photo, or a GIF")
        if self.mentions and self.text is None:
            raise ValueError("Comment mentions require comment text")
        tokens = tuple(mention.token for mention in self.mentions)
        if len({token.casefold() for token in tokens}) != len(tokens):
            raise ValueError("Comment mention tokens must be unique")
        if self.text is not None:
            for token in tokens:
                if self.text.count(token) != 1:
                    raise ValueError(
                        "Each comment mention token must occur exactly once in comment text"
                    )
        return self


class ActionType(StrEnum):
    COMMENT_CREATE = "comment_create"


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


class CommentCreatePayload(StrictModel):
    action_type: Literal[ActionType.COMMENT_CREATE] = ActionType.COMMENT_CREATE
    post_ref: PostReference
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()
    attachment: CommentAttachment | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> CommentCreatePayload:
        if self.text is None and self.attachment is None:
            raise ValueError("A comment payload requires text, a photo, or a GIF")
        return self


class ActionCommand(StrictModel):
    action_type: Literal[ActionType.COMMENT_CREATE] = ActionType.COMMENT_CREATE
    target: ActionTarget
    payload: CommentCreatePayload


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
    action_type: Literal[ActionType.COMMENT_CREATE] = ActionType.COMMENT_CREATE
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
