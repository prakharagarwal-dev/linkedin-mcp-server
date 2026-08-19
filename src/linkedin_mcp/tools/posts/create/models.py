"""Models owned by `linkedin.posts.create`."""

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


AssetReference = Annotated[str, StringConstraints(min_length=1)]


JobId = Annotated[str, StringConstraints(pattern="^[0-9]{5,30}$")]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


CompanySlug = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=200, pattern="^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"
    ),
]


class PostMentionInput(StrictModel):
    token: Annotated[
        str,
        Field(
            min_length=2,
            max_length=500,
            description=(
                "Exact, unique @mention token in the post text. The visible picker must "
                "resolve it to the supplied member or company identity."
            ),
        ),
    ]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostMentionInput:
        if not self.token.startswith("@"):
            raise ValueError("A post mention token must begin with @")
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("A post mention requires exactly one member or company identity")
        return self


class CelebrationType(StrEnum):
    PROJECT_LAUNCH = "project_launch"
    WORK_ANNIVERSARY = "work_anniversary"
    NEW_POSITION = "new_position"
    EDUCATIONAL_MILESTONE = "educational_milestone"
    NEW_CERTIFICATION = "new_certification"


class PostCreateContentBase(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()

    @model_validator(mode="after")
    def validate_mentions(self) -> PostCreateContentBase:
        if self.mentions and self.text is None:
            raise ValueError("Post mentions require post text")
        tokens = tuple(mention.token for mention in self.mentions)
        if len({token.casefold() for token in tokens}) != len(tokens):
            raise ValueError("Post mention tokens must be unique")
        if self.text is not None:
            for token in tokens:
                if self.text.count(token) != 1:
                    raise ValueError(
                        "Each post mention token must occur exactly once in the post text"
                    )
        return self


class PostCreateMode(StrEnum):
    TEXT = "text"
    IMAGES = "images"
    VIDEO = "video"
    DOCUMENT = "document"
    POLL = "poll"
    CELEBRATION = "celebration"
    EVENT = "event"
    HIRING = "hiring"
    EXPERT_REQUEST = "expert_request"


class CelebrationPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.CELEBRATION] = PostCreateMode.CELEBRATION
    celebration_type: CelebrationType
    template_index: Annotated[int, Field(ge=1, le=22)] | None = 1
    image_asset_ref: AssetReference | None = None
    image_alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None

    @model_validator(mode="after")
    def validate_visual(self) -> CelebrationPostContent:
        if self.text is None:
            raise ValueError("A celebration post requires text")
        if (self.template_index is None) == (self.image_asset_ref is None):
            raise ValueError("A celebration requires exactly one LinkedIn template or custom image")
        if self.image_alt_text is not None and self.image_asset_ref is None:
            raise ValueError("Celebration alt text requires a custom image")
        return self


class DocumentPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.DOCUMENT] = PostCreateMode.DOCUMENT
    document_asset_ref: AssetReference
    document_title: Annotated[str, Field(min_length=1, max_length=400)]


class EventFormat(StrEnum):
    LINKEDIN_LIVE = "linkedin_live"
    EXTERNAL_LINK = "external_link"


class EventSpeakerInput(StrictModel):
    profile_slug: ProfileSlug
    display_name: Annotated[str, Field(min_length=1, max_length=500)]


class EventType(StrEnum):
    ONLINE = "online"
    IN_PERSON = "in_person"


class EventPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.EVENT] = PostCreateMode.EVENT
    event_type: EventType
    event_format: EventFormat | None = None
    event_name: Annotated[str, Field(min_length=1, max_length=75)]
    timezone_label: Annotated[str, Field(min_length=1, max_length=200)]
    start_at: datetime
    end_at: datetime | None = None
    external_url: HttpUrl | None = None
    venue_location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    venue_details: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1, max_length=5_000)]
    speakers: Annotated[tuple[EventSpeakerInput, ...], Field(max_length=20)] = ()
    cover_asset_ref: AssetReference | None = None
    cover_alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> EventPostContent:
        if self.text is None:
            raise ValueError("An event post requires text")
        if self.start_at.utcoffset() is None:
            raise ValueError("Event start_at must include a timezone offset")
        if self.end_at is not None:
            if self.end_at.utcoffset() is None:
                raise ValueError("Event end_at must include a timezone offset")
            if self.end_at <= self.start_at:
                raise ValueError("Event end_at must be after start_at")
        if self.event_type is EventType.ONLINE:
            if self.event_format is None:
                raise ValueError("An online event requires an event format")
            if self.event_format is EventFormat.EXTERNAL_LINK and self.external_url is None:
                raise ValueError("An external online event requires external_url")
            if self.event_format is EventFormat.LINKEDIN_LIVE and self.external_url is not None:
                raise ValueError("A LinkedIn Live event cannot include external_url")
            if self.venue_location is not None or self.venue_details is not None:
                raise ValueError("Online events cannot include an in-person venue")
        else:
            if self.event_format is not None:
                raise ValueError("An in-person event does not use an online event format")
            if self.venue_location is None:
                raise ValueError("An in-person event requires venue_location")
        if self.cover_alt_text is not None and self.cover_asset_ref is None:
            raise ValueError("Event cover alt text requires a cover image")
        slugs = tuple(speaker.profile_slug for speaker in self.speakers)
        if len(set(slugs)) != len(slugs):
            raise ValueError("Event speakers must be unique")
        return self


class ExpertRequestCategory(StrEnum):
    ACCOUNTING = "accounting"
    COACHING_AND_MENTORING = "coaching_and_mentoring"
    DESIGN = "design"
    MARKETING = "marketing"
    OTHER = "other"


class ExpertRequestPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.EXPERT_REQUEST] = PostCreateMode.EXPERT_REQUEST
    category: ExpertRequestCategory
    location_label: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_description(self) -> ExpertRequestPostContent:
        if self.text is None or not 25 <= len(self.text) <= 750:
            raise ValueError("An expert-request description must be 25 to 750 characters")
        return self


class HiringPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.HIRING] = PostCreateMode.HIRING
    company_name: Annotated[str, Field(min_length=1, max_length=500)]
    job_id: JobId
    job_title: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def require_text(self) -> HiringPostContent:
        if self.text is None:
            raise ValueError("A hiring post requires text")
        return self


class PostImageAspectRatio(StrEnum):
    ORIGINAL = "original"
    SQUARE = "square"
    FOUR_TO_ONE = "four_to_one"
    THREE_TO_FOUR = "three_to_four"
    SIXTEEN_TO_NINE = "sixteen_to_nine"


class PostImageFilter(StrEnum):
    ORIGINAL = "original"
    STUDIO = "studio"
    SPOTLIGHT = "spotlight"
    PRIME = "prime"
    CLASSIC = "classic"
    EDGE = "edge"
    LUMINATE = "luminate"


class PostImageEditInput(StrictModel):
    """Exact controls exposed by LinkedIn's current desktop image editor."""

    clockwise_quarter_turns: Annotated[int, Field(ge=-3, le=3)] = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    aspect_ratio: PostImageAspectRatio = PostImageAspectRatio.ORIGINAL
    zoom: Annotated[float, Field(ge=1.0, le=3.0, multiple_of=0.1)] = 1.0
    straighten_degrees: Annotated[int, Field(ge=-45, le=45)] = 0
    image_filter: PostImageFilter = PostImageFilter.ORIGINAL
    brightness: Annotated[int, Field(ge=-30, le=30)] = 0
    contrast: Annotated[int, Field(ge=-30, le=30)] = 0
    saturation: Annotated[int, Field(ge=-30, le=30)] = 0
    vignette: Annotated[int, Field(ge=-30, le=30)] = 0


class PostImageTagInput(StrictModel):
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostImageTagInput:
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("An image tag requires exactly one member or company identity")
        return self


class PostImageInput(StrictModel):
    asset_ref: AssetReference
    alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    tags: Annotated[
        tuple[PostImageTagInput, ...],
        Field(max_length=30),
    ] = ()
    edit: PostImageEditInput | None = None

    @model_validator(mode="after")
    def reject_duplicate_tags(self) -> PostImageInput:
        identities = tuple(
            (
                "member",
                member.profile_slug,
            )
            if member.profile_slug is not None
            else ("company", member.company_slug)
            for member in self.tags
        )
        if len(set(identities)) != len(identities):
            raise ValueError("Image tags must be unique")
        return self


class ImagePostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.IMAGES] = PostCreateMode.IMAGES
    images: Annotated[tuple[PostImageInput, ...], Field(min_length=1, max_length=20)]


class PollDuration(StrEnum):
    ONE_DAY = "one_day"
    THREE_DAYS = "three_days"
    ONE_WEEK = "one_week"
    TWO_WEEKS = "two_weeks"


class PollPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.POLL] = PostCreateMode.POLL
    question: Annotated[str, Field(min_length=1, max_length=140)]
    options: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=30)], ...],
        Field(min_length=2, max_length=4),
    ]
    duration: PollDuration = PollDuration.ONE_WEEK

    @model_validator(mode="after")
    def reject_duplicate_options(self) -> PollPostContent:
        if len({option.casefold() for option in self.options}) != len(self.options):
            raise ValueError("Poll options must be unique")
        return self


class PostAudience(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    GROUP = "group"


class PostCollaboratorInput(StrictModel):
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostCollaboratorInput:
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("A post collaborator requires exactly one member or company identity")
        return self


class PostCommentControl(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    NO_ONE = "no_one"


class TextPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.TEXT] = PostCreateMode.TEXT
    link_url: HttpUrl | None = None
    show_link_preview: bool = True

    @model_validator(mode="after")
    def validate_link(self) -> TextPostContent:
        if self.text is None:
            raise ValueError("A text post requires text")
        if self.link_url is None and not self.show_link_preview:
            raise ValueError("A link preview can be removed only when link_url is supplied")
        if self.link_url is not None and str(self.link_url) not in self.text:
            raise ValueError("link_url must occur exactly in the post text")
        return self


class VideoCaptionMode(StrEnum):
    NONE = "none"
    AUTO = "auto"
    FILE = "file"


class VideoPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.VIDEO] = PostCreateMode.VIDEO
    video_asset_ref: AssetReference
    thumbnail_asset_ref: AssetReference | None = None
    caption_mode: VideoCaptionMode = VideoCaptionMode.NONE
    caption_asset_ref: AssetReference | None = None
    review_auto_captions: bool = False

    @model_validator(mode="after")
    def validate_caption_options(self) -> VideoPostContent:
        if self.caption_mode is VideoCaptionMode.FILE and self.caption_asset_ref is None:
            raise ValueError("File captions require caption_asset_ref")
        if self.caption_mode is not VideoCaptionMode.FILE and self.caption_asset_ref is not None:
            raise ValueError("caption_asset_ref is valid only for file captions")
        if self.caption_mode is not VideoCaptionMode.AUTO and self.review_auto_captions:
            raise ValueError("review_auto_captions requires automatic captions")
        refs = tuple(
            value
            for value in (
                self.video_asset_ref,
                self.thumbnail_asset_ref,
                self.caption_asset_ref,
            )
            if value is not None
        )
        if len(set(refs)) != len(refs):
            raise ValueError("Video, thumbnail, and caption assets must be distinct")
        return self


PostCreateContent = Annotated[
    TextPostContent
    | ImagePostContent
    | VideoPostContent
    | DocumentPostContent
    | PollPostContent
    | CelebrationPostContent
    | EventPostContent
    | HiringPostContent
    | ExpertRequestPostContent,
    Field(
        discriminator="mode",
        description=(
            "Typed post content discriminated by the required mode field; use mode, not kind."
        ),
    ),
]


class PostGroupTarget(StrictModel):
    group_id: Annotated[str, Field(pattern=r"^[0-9]{3,30}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=500)]


class PostCreateInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    content: PostCreateContent
    audience: PostAudience = PostAudience.ANYONE
    group_target: PostGroupTarget | None = None
    comment_control: PostCommentControl = PostCommentControl.ANYONE
    brand_partnership: bool = False
    collaborators: Annotated[tuple[PostCollaboratorInput, ...], Field(max_length=5)] = ()
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule_shape(self) -> PostCreateInput:
        if self.scheduled_at is not None and self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        if (self.audience is PostAudience.GROUP) != (self.group_target is not None):
            raise ValueError("Group audience requires exactly one group_target")
        if self.brand_partnership and self.audience is not PostAudience.ANYONE:
            raise ValueError("Brand partnership posts must use the Anyone audience")
        if self.collaborators and self.audience is not PostAudience.ANYONE:
            raise ValueError("Collaborative posts must use the Anyone audience")
        collaborator_identities = tuple(
            ("member", collaborator.profile_slug)
            if collaborator.profile_slug is not None
            else ("company", collaborator.company_slug)
            for collaborator in self.collaborators
        )
        if len(set(collaborator_identities)) != len(collaborator_identities):
            raise ValueError("Post collaborators must be unique")
        if self.scheduled_at is not None and isinstance(
            self.content,
            EventPostContent | HiringPostContent | ExpertRequestPostContent,
        ):
            raise ValueError("LinkedIn does not schedule event, hiring, or expert-request posts")
        return self


class ActionType(StrEnum):
    POST_CREATE = "post_create"


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
    def validate_payload(self) -> PostCreatePayload:
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


class ActionCommand(StrictModel):
    action_type: Literal[ActionType.POST_CREATE] = ActionType.POST_CREATE
    target: ActionTarget
    payload: PostCreatePayload


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
    action_type: Literal[ActionType.POST_CREATE] = ActionType.POST_CREATE
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
