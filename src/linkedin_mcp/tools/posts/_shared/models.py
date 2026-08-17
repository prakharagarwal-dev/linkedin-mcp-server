from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
    CommentReference,
    CompanySlug,
    Identifier,
    JobId,
    LinkedInFacetIds,
    LinkedInFacetLabels,
    PaginatedInput,
    PaginationMetadata,
    PostReference,
    ProfileSlug,
    SourceReference,
    StopReason,
    StrictModel,
)


class PostAuthorType(StrEnum):
    MEMBER = "member"
    COMPANY = "company"
    UNKNOWN = "unknown"


class PostSearchSort(StrEnum):
    TOP_MATCH = "top_match"
    LATEST = "latest"


class PostSearchDate(StrEnum):
    ANY_TIME = "any_time"
    PAST_24_HOURS = "past_24_hours"
    PAST_WEEK = "past_week"
    PAST_MONTH = "past_month"


class PostSearchContentType(StrEnum):
    VIDEOS = "videos"
    IMAGES = "images"
    JOB_POSTS = "job_posts"
    LIVE_VIDEOS = "live_videos"
    DOCUMENTS = "documents"


class PostContentType(StrEnum):
    TEXT = "text"
    LINK = "link"
    ARTICLE = "article"
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    LIVE_VIDEO = "live_video"
    NEWSLETTER = "newsletter"
    EVENT = "event"
    JOB = "job"
    POLL = "poll"
    REPOST = "repost"
    CELEBRATION = "celebration"
    OTHER = "other"


class PostPollState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


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


class PostAudience(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    GROUP = "group"


class PostCommentControl(StrEnum):
    ANYONE = "anyone"
    CONNECTIONS_ONLY = "connections_only"
    NO_ONE = "no_one"


class PollDuration(StrEnum):
    ONE_DAY = "one_day"
    THREE_DAYS = "three_days"
    ONE_WEEK = "one_week"
    TWO_WEEKS = "two_weeks"


class VideoCaptionMode(StrEnum):
    NONE = "none"
    AUTO = "auto"
    FILE = "file"


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


class CelebrationType(StrEnum):
    PROJECT_LAUNCH = "project_launch"
    WORK_ANNIVERSARY = "work_anniversary"
    NEW_POSITION = "new_position"
    EDUCATIONAL_MILESTONE = "educational_milestone"
    NEW_CERTIFICATION = "new_certification"


class EventType(StrEnum):
    ONLINE = "online"
    IN_PERSON = "in_person"


class EventFormat(StrEnum):
    LINKEDIN_LIVE = "linkedin_live"
    EXTERNAL_LINK = "external_link"


class ExpertRequestCategory(StrEnum):
    ACCOUNTING = "accounting"
    COACHING_AND_MENTORING = "coaching_and_mentoring"
    DESIGN = "design"
    MARKETING = "marketing"
    OTHER = "other"


class PostAssetRole(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    VIDEO_THUMBNAIL = "video_thumbnail"
    VIDEO_CAPTIONS = "video_captions"
    DOCUMENT = "document"
    CELEBRATION_IMAGE = "celebration_image"
    EVENT_COVER_IMAGE = "event_cover_image"
    COMMENT_IMAGE = "comment_image"
    MESSAGE_ATTACHMENT = "message_attachment"


class CommentAttachmentType(StrEnum):
    PHOTO = "photo"
    GIF = "gif"


class ReactionState(StrEnum):
    NONE = "none"
    LIKE = "like"
    CELEBRATE = "celebrate"
    SUPPORT = "support"
    LOVE = "love"
    INSIGHTFUL = "insightful"
    FUNNY = "funny"


class PostSearchPostedBy(StrEnum):
    ME = "me"
    FIRST_CONNECTIONS = "first_connections"
    PEOPLE_YOU_FOLLOW = "people_you_follow"


class CommentSort(StrEnum):
    MOST_RELEVANT = "most_relevant"
    MOST_RECENT = "most_recent"


class PostSearchFilters(StrictModel):
    """Every filter in LinkedIn's current visible Posts All-filters panel."""

    sort_by: PostSearchSort = Field(
        default=PostSearchSort.TOP_MATCH,
        description="Sort by LinkedIn's visible Top Match or Latest choice.",
    )
    date_posted: PostSearchDate = Field(
        default=PostSearchDate.ANY_TIME,
        description=(
            "Limit posts to the past 24 hours, week, or month; Any time leaves "
            "LinkedIn's date filter unset."
        ),
    )
    content_type: PostSearchContentType | None = Field(
        default=None,
        description=(
            "One current visible content type: videos, images, job posts, live videos, "
            "or documents."
        ),
    )
    from_member_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn member facet IDs for From member.",
    )
    from_member_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible From member picker.",
    )
    from_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn organization facet IDs for From company.",
    )
    from_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through the visible From company picker.",
    )
    posted_by: Annotated[
        tuple[PostSearchPostedBy, ...],
        Field(max_length=len(PostSearchPostedBy)),
    ] = Field(
        default=(),
        description="Posts by the configured member, first-degree connections, and/or follows.",
    )
    mentioning_member_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact member facet IDs for Mentioning member.",
    )
    mentioning_member_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Mentioning member picker.",
    )
    mentioning_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact organization facet IDs for Mentioning company.",
    )
    mentioning_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through the visible Mentioning company picker.",
    )
    author_industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact industry facet IDs for Author industry.",
    )
    author_industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industries to resolve through the visible Author industry picker.",
    )
    author_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact organization facet IDs for Author company.",
    )
    author_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Companies to resolve through the visible Author company picker.",
    )
    author_keywords: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Author Keywords text applied to the author's title.",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_filters(self) -> PostSearchFilters:
        sequence_fields = (
            "from_member_ids",
            "from_member_names",
            "from_company_ids",
            "from_company_names",
            "posted_by",
            "mentioning_member_ids",
            "mentioning_member_names",
            "mentioning_company_ids",
            "mentioning_company_names",
            "author_industry_ids",
            "author_industry_names",
            "author_company_ids",
            "author_company_names",
        )
        for field_name in sequence_fields:
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            ("from_member_ids", "from_member_names"),
            ("from_company_ids", "from_company_names"),
            ("mentioning_member_ids", "mentioning_member_names"),
            ("mentioning_company_ids", "mentioning_company_names"),
            ("author_industry_ids", "author_industry_names"),
            ("author_company_ids", "author_company_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        return self

    def has_constraints(self) -> bool:
        return (
            self.date_posted is not PostSearchDate.ANY_TIME
            or self.content_type is not None
            or bool(self.posted_by)
            or self.author_keywords is not None
            or any(
                getattr(self, field_name)
                for field_name in (
                    "from_member_ids",
                    "from_member_names",
                    "from_company_ids",
                    "from_company_names",
                    "mentioning_member_ids",
                    "mentioning_member_names",
                    "mentioning_company_ids",
                    "mentioning_company_names",
                    "author_industry_ids",
                    "author_industry_names",
                    "author_company_ids",
                    "author_company_names",
                )
            )
        )


class PostSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PostSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Post search requires query or at least one substantive filter")
        return self


class PostGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference


class PostCommentsListInput(PaginatedInput):
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum top-level comment threads returned in this page.",
        ),
    ] = 25
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    sort_by: CommentSort = CommentSort.MOST_RELEVANT
    max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25


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


class PostImageTagInput(StrictModel):
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostImageTagInput:
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("An image tag requires exactly one member or company identity")
        return self


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


class DocumentPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.DOCUMENT] = PostCreateMode.DOCUMENT
    document_asset_ref: AssetReference
    document_title: Annotated[str, Field(min_length=1, max_length=400)]


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


class EventSpeakerInput(StrictModel):
    profile_slug: ProfileSlug
    display_name: Annotated[str, Field(min_length=1, max_length=500)]


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


class ExpertRequestPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.EXPERT_REQUEST] = PostCreateMode.EXPERT_REQUEST
    category: ExpertRequestCategory
    location_label: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def validate_description(self) -> ExpertRequestPostContent:
        if self.text is None or not 25 <= len(self.text) <= 750:
            raise ValueError("An expert-request description must be 25 to 750 characters")
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


class PostCollaboratorInput(StrictModel):
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostCollaboratorInput:
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("A post collaborator requires exactly one member or company identity")
        return self


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


class CommentPhotoAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.PHOTO] = CommentAttachmentType.PHOTO
    asset_ref: AssetReference


class CommentGifAttachment(StrictModel):
    attachment_type: Literal[CommentAttachmentType.GIF] = CommentAttachmentType.GIF
    search_query: Annotated[str, Field(min_length=1, max_length=200)]
    visible_result_label: Annotated[str, Field(min_length=1, max_length=500)]


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


class PostReactionInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    desired_reaction: ReactionState


class PostAuthor(StrictModel):
    author_type: PostAuthorType
    name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None
    author_url: HttpUrl | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    relationship_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    verified: bool = False
    viewer_is_author: bool = False

    @model_validator(mode="after")
    def validate_typed_identity(self) -> PostAuthor:
        if self.author_type is PostAuthorType.MEMBER and not self.profile_slug:
            raise ValueError("A member post author requires profile_slug")
        if self.author_type is PostAuthorType.COMPANY and not self.company_slug:
            raise ValueError("A company post author requires company_slug")
        return self


class PostLink(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=2_000)]
    url: HttpUrl


class PostAttachment(StrictModel):
    content_type: PostContentType
    label: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    url: HttpUrl | None = None
    preview_url: HttpUrl | None = None
    page_count: Annotated[int, Field(ge=1, le=10_000)] | None = None
    duration_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> PostAttachment:
        if not any((self.label, self.url, self.preview_url, self.visible_text)):
            raise ValueError(
                "A post attachment requires visible identity or a visible resource URL"
            )
        if self.page_count is not None and self.content_type is not PostContentType.DOCUMENT:
            raise ValueError("Only a document attachment can expose page_count")
        return self


class PostPollOption(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    percentage_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    vote_count_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    selected: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostPoll(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    options: Annotated[tuple[PostPollOption, ...], Field(min_length=2, max_length=5)]
    total_votes_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    state: PostPollState = PostPollState.UNKNOWN
    state_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    viewer_has_voted: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_options(self) -> PostPoll:
        normalized = tuple(option.text.casefold() for option in self.options)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Visible poll options must be unique")
        return self


class PostResharedContent(StrictModel):
    post_ref: PostReference | None = None
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    content_type: PostContentType = PostContentType.TEXT
    attachments: tuple[PostAttachment, ...] = ()
    links: tuple[PostLink, ...] = ()
    hashtags: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = ()
    mentions: tuple[PostLink, ...] = ()
    poll: PostPoll | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    captured_at: datetime


class PostSummary(StrictModel):
    post_ref: PostReference
    post_url: HttpUrl
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    content_type: PostContentType = PostContentType.TEXT
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comment_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    repost_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostSearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unsupported_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Selected visible post cards omitted because their stable post or author "
            "identity is outside the typed public contract."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class PostSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    posts: tuple[PostSummary, ...]
    coverage: PostSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class PostDetailCoverage(StrictModel):
    requested_post_ref: PostReference
    displayed_post_ref: PostReference
    pages_visited: Annotated[int, Field(ge=1, le=2)]
    source_urls: Annotated[tuple[HttpUrl, ...], Field(min_length=1, max_length=2)]
    text_expanded: bool
    attachment_count: Annotated[int, Field(ge=0)]
    link_count: Annotated[int, Field(ge=0)]
    mention_count: Annotated[int, Field(ge=0)]
    hashtag_count: Annotated[int, Field(ge=0)]
    poll_present: bool
    reshared_post_present: bool
    truncated: Literal[False] = False
    captured_at: datetime

    @model_validator(mode="after")
    def validate_source_pages(self) -> PostDetailCoverage:
        if len(self.source_urls) != self.pages_visited:
            raise ValueError("Post detail source URLs conflict with pages_visited")
        if len({str(url) for url in self.source_urls}) != len(self.source_urls):
            raise ValueError("Post detail source URLs must be unique")
        return self


class PostObservation(StrictModel):
    post_ref: PostReference
    displayed_post_ref: PostReference
    post_url: HttpUrl
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    visibility_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    promoted: bool = False
    content_type: PostContentType = PostContentType.TEXT
    attachments: tuple[PostAttachment, ...] = ()
    links: tuple[PostLink, ...] = ()
    hashtags: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...] = ()
    mentions: tuple[PostLink, ...] = ()
    poll: PostPoll | None = None
    reshared_post: PostResharedContent | None = None
    viewer_reaction: ReactionState | None = None
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comment_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    repost_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    impression_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comments_enabled: bool = False
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[PostEvidence, ...]
    coverage: PostDetailCoverage
    captured_at: datetime

    @model_validator(mode="after")
    def validate_detail_consistency(self) -> PostObservation:
        if self.coverage.requested_post_ref != self.post_ref:
            raise ValueError("Post detail coverage conflicts with the requested post reference")
        if self.coverage.displayed_post_ref != self.displayed_post_ref:
            raise ValueError("Post detail coverage conflicts with the displayed post reference")
        if self.coverage.attachment_count != len(self.attachments):
            raise ValueError("Post detail coverage conflicts with the attachment count")
        if self.coverage.link_count != len(self.links):
            raise ValueError("Post detail coverage conflicts with the link count")
        if self.coverage.mention_count != len(self.mentions):
            raise ValueError("Post detail coverage conflicts with the mention count")
        if self.coverage.hashtag_count != len(self.hashtags):
            raise ValueError("Post detail coverage conflicts with the hashtag count")
        if self.coverage.poll_present != (self.poll is not None):
            raise ValueError("Post detail coverage conflicts with the poll state")
        if self.coverage.reshared_post_present != (self.reshared_post is not None):
            raise ValueError("Post detail coverage conflicts with the reshared-post state")
        if self.coverage.captured_at != self.captured_at:
            raise ValueError("Post detail coverage conflicts with the capture time")
        if str(self.coverage.source_urls[0]) != str(self.post_url):
            raise ValueError("Post detail coverage conflicts with the requested source URL")
        if (self.content_type is PostContentType.POLL) != (self.poll is not None):
            raise ValueError("Post poll type and visible poll details must agree")
        if (self.content_type is PostContentType.REPOST) != (self.reshared_post is not None):
            raise ValueError("Post repost type and visible reshared-post details must agree")
        if (self.coverage.pages_visited == 2) != (self.reshared_post is not None):
            raise ValueError("A repost must capture exactly the wrapper and original pages")
        source_urls = {str(url) for url in self.coverage.source_urls}
        for evidence in self.evidence:
            if (
                str(evidence.source_url) not in source_urls
                or evidence.captured_at != self.captured_at
            ):
                raise ValueError("Post evidence conflicts with the detail capture")
        return self


class PostGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    post: PostObservation
    sources: tuple[SourceReference, ...]


class CommentAttachmentObservation(StrictModel):
    attachment_type: CommentAttachmentType
    accessible_label: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    resource_url: HttpUrl | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> CommentAttachmentObservation:
        if self.accessible_label is None and self.resource_url is None:
            raise ValueError("A comment attachment requires visible identity evidence")
        return self


class CommentObservation(StrictModel):
    comment_ref: CommentReference
    post_ref: PostReference
    parent_comment_ref: CommentReference | None = None
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    attachments: Annotated[
        tuple[CommentAttachmentObservation, ...],
        Field(max_length=10),
    ] = ()
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    reply_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_comment_content(self) -> CommentObservation:
        if self.text is None and not self.attachments:
            raise ValueError("A comment observation requires text or a visible attachment")
        return self


class CommentThread(StrictModel):
    comment: CommentObservation
    replies: tuple[CommentObservation, ...] = ()


class PostCommentsCoverage(StrictModel):
    post_ref: PostReference
    discussion_post_ref: PostReference
    sort_by: CommentSort
    expansion_rounds: Annotated[int, Field(ge=0)]
    top_level_visible: Annotated[int, Field(ge=0)]
    top_level_returned: Annotated[int, Field(ge=0)]
    replies_visible: Annotated[int, Field(ge=0)]
    replies_returned: Annotated[int, Field(ge=0)]
    max_comments: Annotated[int, Field(ge=1)]
    max_replies_per_comment: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime


class PostCommentsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    threads: tuple[CommentThread, ...]
    coverage: PostCommentsCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
