"""Validated data contracts for the public MCP surface and internal evidence."""

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

from linkedin_mcp.domain.identifiers import PROFILE_SLUG_PATTERN


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


PaginationCursor = Annotated[
    str,
    StringConstraints(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class PaginatedInput(StrictModel):
    """Shared public cursor contract for bounded collection capabilities."""

    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum unique items returned in this page.",
        ),
    ] = 25
    cursor: (
        Annotated[
            PaginationCursor,
            Field(
                description=(
                    "Opaque continuation cursor from the immediately preceding page. "
                    "Cursors are process-local, single-use, filter-bound, and expiring."
                )
            ),
        ]
        | None
    ) = None


Identifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
AssetReference = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=500,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,499}$",
    ),
]
JobId = Annotated[str, StringConstraints(pattern=r"^[0-9]{5,30}$")]
ProfileSlug = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=PROFILE_SLUG_PATTERN,
    ),
]
CompanySlug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$",
    ),
]
PostReference = Annotated[
    str,
    StringConstraints(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
]
CommentReference = Annotated[
    str,
    StringConstraints(pattern=r"^comment:(?:activity|share|ugc-post):[0-9]{5,30}:[0-9]{1,30}$"),
]
ConversationId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=500,
        pattern=r"^[A-Za-z0-9_%=-]+$",
    ),
]
LinkedInFacetId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]
LinkedInFacetIds = Annotated[
    tuple[LinkedInFacetId, ...],
    Field(max_length=10),
]
LinkedInFacetLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
LinkedInFacetLabels = Annotated[
    tuple[LinkedInFacetLabel, ...],
    Field(max_length=10),
]


class CapabilityEffect(StrEnum):
    READ = "read"
    WRITE = "write"


class CapabilityName(StrEnum):
    JOBS_SEARCH = "linkedin.jobs.search"
    JOBS_GET = "linkedin.jobs.get"
    PEOPLE_SEARCH = "linkedin.people.search"
    PEOPLE_GET = "linkedin.people.get"
    COMPANIES_SEARCH = "linkedin.companies.search"
    COMPANIES_GET = "linkedin.companies.get"
    POSTS_SEARCH = "linkedin.posts.search"
    POSTS_GET = "linkedin.posts.get"
    POST_COMMENTS_LIST = "linkedin.posts.comments.list"
    POSTS_CREATE = "linkedin.posts.create"
    POST_COMMENT = "linkedin.posts.comment"
    POST_REACT = "linkedin.posts.react"
    INVITATIONS_LIST = "linkedin.invitations.list"
    CONNECTIONS_LIST = "linkedin.connections.list"
    CONNECTIONS_SEARCH = "linkedin.connections.search"
    INVITATION_SEND = "linkedin.invitations.send"
    INVITATION_ACCEPT = "linkedin.invitations.accept"
    INVITATION_IGNORE = "linkedin.invitations.ignore"
    MESSAGING_SEARCH = "linkedin.messaging.search"
    MESSAGING_CONVERSATION_GET = "linkedin.messaging.conversation.get"
    MESSAGING_SEND = "linkedin.messaging.send"


class LinkedInSurface(StrEnum):
    JOB_SEARCH = "job-search"
    JOB_DETAIL = "job-detail"
    PEOPLE_SEARCH = "people-search"
    MEMBER_PROFILE = "member-profile"
    COMPANY_SEARCH = "company-search"
    COMPANY_PROFILE = "company-profile"
    COMPANY_ABOUT = "company-about"
    CONTENT_SEARCH = "content-search"
    POST_DETAIL = "post-detail"
    POST_DISCUSSION = "post-discussion"
    POST_COMPOSER = "post-composer"
    MESSAGING = "messaging"
    CONNECTIONS = "connections"
    JOB_APPLICATION = "job-application"


class SourceType(StrEnum):
    JOB_SEARCH = "linkedin_job_search"
    JOB = "linkedin_job"
    PEOPLE_SEARCH = "linkedin_people_search"
    MEMBER_PROFILE = "linkedin_member_profile"
    COMPANY_SEARCH = "linkedin_company_search"
    COMPANY_PROFILE = "linkedin_company_profile"
    POST_SEARCH = "linkedin_post_search"
    POST = "linkedin_post"
    POST_COMMENTS = "linkedin_post_comments"
    INVITATIONS = "linkedin_invitations"
    CONNECTIONS = "linkedin_connections"
    MESSAGING_INBOX = "linkedin_messaging_inbox"
    MESSAGING_CONVERSATION = "linkedin_messaging_conversation"
    ACTION_EXECUTION = "linkedin_action_execution"


class StopReason(StrEnum):
    RESULT_LIMIT = "result_limit"
    SAFETY_BOUND = "safety_bound"
    NO_NEW_RESULTS = "no_new_results"
    VISIBLE_PAGE_COMPLETE = "visible_page_complete"


class PersonConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"
    OUT_OF_NETWORK = "out_of_network"


class PeopleSearchConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"


class PersonProfileSectionSelector(StrEnum):
    ALL = "all"
    OVERVIEW = "overview"
    ABOUT = "about"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LICENSES_CERTIFICATIONS = "licenses-certifications"
    PROJECTS = "projects"
    VOLUNTEERING = "volunteering"
    SKILLS = "skills"
    INTERESTS = "interests"
    FEATURED = "featured"
    COURSES = "courses"
    HONORS_AWARDS = "honors-awards"
    LANGUAGES = "languages"
    ORGANIZATIONS = "organizations"
    PUBLICATIONS = "publications"
    PATENTS = "patents"
    RECOMMENDATIONS = "recommendations"
    TEST_SCORES = "test-scores"


class CompanySize(StrEnum):
    EMPLOYEES_1_10 = "1-10"
    EMPLOYEES_11_50 = "11-50"
    EMPLOYEES_51_200 = "51-200"
    EMPLOYEES_201_500 = "201-500"
    EMPLOYEES_501_1000 = "501-1000"
    EMPLOYEES_1001_5000 = "1001-5000"
    EMPLOYEES_5001_10000 = "5001-10000"
    EMPLOYEES_10001_PLUS = "10001+"


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


class InvitationDirection(StrEnum):
    RECEIVED = "received"
    SENT = "sent"


class InvitationFilter(StrEnum):
    ALL = "all"
    FOCUSED = "focused"
    OTHER = "other"
    VERIFIED = "verified"
    SAME_COMPANY = "same_company"
    SAME_SCHOOL = "same_school"
    MUTUAL_CONNECTIONS = "mutual_connections"
    PEOPLE = "people"


CURRENT_RECEIVED_INVITATION_VIEWS: tuple[InvitationFilter, ...] = (
    InvitationFilter.FOCUSED,
    InvitationFilter.OTHER,
    InvitationFilter.VERIFIED,
    InvitationFilter.MUTUAL_CONNECTIONS,
    InvitationFilter.SAME_COMPANY,
    InvitationFilter.SAME_SCHOOL,
)


class InvitationEntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    SCHOOL = "school"
    GROUP = "group"
    EVENT = "event"
    NEWSLETTER = "newsletter"
    OTHER = "other"


class InvitationType(StrEnum):
    CONNECTION_REQUEST = "connection_request"
    COMPANY_FOLLOW = "company_follow"
    SCHOOL_INVITATION = "school_invitation"
    GROUP_INVITATION = "group_invitation"
    EVENT_INVITATION = "event_invitation"
    NEWSLETTER_INVITATION = "newsletter_invitation"
    OTHER = "other"


class InvitationAvailableAction(StrEnum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    WITHDRAW = "withdraw"
    MESSAGE = "message"
    REPLY = "reply"


class ConnectionsSortBy(StrEnum):
    RECENTLY_ADDED = "recently_added"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"


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


class SessionAuthenticationState(StrEnum):
    UNVERIFIED = "unverified"
    LOGIN_REQUIRED = "login_required"
    LOGIN_IN_PROGRESS = "login_in_progress"
    VALIDATING = "validating"
    AUTHENTICATED = "authenticated"
    ATTENTION_REQUIRED = "attention_required"


class BrowserSetupState(StrEnum):
    DISABLED = "disabled"
    NOT_STARTED = "not_started"
    INSTALLING = "installing"
    READY = "ready"
    FAILED = "failed"


class MessageAttachmentKind(StrEnum):
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"


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


class _PeopleSearchFilterBase(StrictModel):
    """Shared non-degree filters from LinkedIn's visible People-filter side panel."""

    actively_hiring: bool = Field(
        default=False,
        description="Match people visibly hiring for any job title.",
    )
    actively_hiring_job_title_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible Actively-hiring job-title facet IDs.",
    )
    actively_hiring_job_title_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Job titles to resolve through LinkedIn's visible Hiring for job title picker."
        ),
    )
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn geography facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description="Locations to resolve through LinkedIn's visible location picker.",
    )
    current_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact current-company facet IDs.",
    )
    current_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Current companies to resolve through the visible company picker.",
    )
    connections_of_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible member facet IDs for Connections of.",
    )
    connections_of_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Connections of picker.",
    )
    followers_of_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible member facet IDs for Followers of.",
    )
    followers_of_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Followers of picker.",
    )
    past_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact past-company facet IDs.",
    )
    past_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Past companies to resolve through the visible company picker.",
    )
    school_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn school facet IDs.",
    )
    school_names: LinkedInFacetLabels = Field(
        default=(),
        description="Schools to resolve through LinkedIn's visible school picker.",
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industries to resolve through LinkedIn's visible industry picker.",
    )
    profile_language_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible profile-language codes.",
    )
    profile_language_names: LinkedInFacetLabels = Field(
        default=(),
        description="Profile languages to resolve from current visible choices.",
    )
    service_category_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible service-category facet IDs.",
    )
    service_category_names: LinkedInFacetLabels = Field(
        default=(),
        description="Service categories to resolve through the visible services picker.",
    )
    first_name: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible First name keyword filter.",
            ),
        ]
        | None
    ) = None
    last_name: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible Last name keyword filter.",
            ),
        ]
        | None
    ) = None
    title: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Title keyword filter.",
            ),
        ]
        | None
    ) = None
    company: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Company keyword filter.",
            ),
        ]
        | None
    ) = None
    school: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible School keyword filter.",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def reject_duplicate_or_unbounded_values(self) -> _PeopleSearchFilterBase:
        sequence_fields = (
            "actively_hiring_job_title_ids",
            "actively_hiring_job_title_names",
            "location_ids",
            "location_names",
            "current_company_ids",
            "current_company_names",
            "connections_of_ids",
            "connections_of_names",
            "followers_of_ids",
            "followers_of_names",
            "past_company_ids",
            "past_company_names",
            "school_ids",
            "school_names",
            "industry_ids",
            "industry_names",
            "profile_language_ids",
            "profile_language_names",
            "service_category_ids",
            "service_category_names",
        )
        for field_name in sequence_fields:
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            (
                "actively_hiring_job_title_ids",
                "actively_hiring_job_title_names",
            ),
            ("location_ids", "location_names"),
            ("current_company_ids", "current_company_names"),
            ("connections_of_ids", "connections_of_names"),
            ("followers_of_ids", "followers_of_names"),
            ("past_company_ids", "past_company_names"),
            ("school_ids", "school_names"),
            ("industry_ids", "industry_names"),
            ("profile_language_ids", "profile_language_names"),
            ("service_category_ids", "service_category_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        if self.actively_hiring and (
            self.actively_hiring_job_title_ids or self.actively_hiring_job_title_names
        ):
            raise ValueError(
                "actively_hiring cannot be combined with specific actively-hiring job titles"
            )
        return self

    def has_constraints(self) -> bool:
        return any(value for _, value in self)


class PeopleSearchFilters(_PeopleSearchFilterBase):
    """All-network filters from LinkedIn's current visible People-filter side panel."""

    connection_degrees: Annotated[
        tuple[PeopleSearchConnectionDegree, ...],
        Field(max_length=3),
    ] = Field(
        default=(),
        description="First-, second-, and/or third-plus-degree visible network filters.",
    )

    @model_validator(mode="after")
    def reject_duplicate_degrees(self) -> PeopleSearchFilters:
        if len(set(self.connection_degrees)) != len(self.connection_degrees):
            raise ValueError("connection_degrees cannot contain duplicate values")
        return self


class ConnectionsSearchFilters(_PeopleSearchFilterBase):
    """People filters for established connections; first degree is server-enforced."""

    def as_people_search_filters(self) -> PeopleSearchFilters:
        return PeopleSearchFilters.model_validate(
            {
                **self.model_dump(mode="python"),
                "connection_degrees": (PeopleSearchConnectionDegree.FIRST,),
            }
        )


class PeopleSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for visible People search.",
            ),
        ]
        | None
    ) = None
    filters: PeopleSearchFilters = Field(
        default_factory=PeopleSearchFilters,
        description="Optional structured filters from LinkedIn's visible People search.",
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PeopleSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("People search requires query or at least one filter")
        return self


class PeopleGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
    sections: Annotated[
        tuple[PersonProfileSectionSelector, ...],
        Field(
            min_length=1,
            max_length=len(PersonProfileSectionSelector),
            description=(
                "Visible profile sections to return. 'all' preserves the complete bounded "
                "profile read and cannot be combined with another selector."
            ),
        ),
    ] = (PersonProfileSectionSelector.ALL,)

    @model_validator(mode="after")
    def validate_sections(self) -> PeopleGetInput:
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Profile section selectors must not contain duplicates")
        if PersonProfileSectionSelector.ALL in self.sections and len(self.sections) != 1:
            raise ValueError("'all' cannot be combined with another profile section")
        return self


class CompanySearchFilters(StrictModel):
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Stable LinkedIn headquarters-location facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Exact visible headquarters-location labels resolved through LinkedIn's "
            "Company-search filter UI."
        ),
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Stable LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Exact visible industry labels resolved through LinkedIn's Company-search filter UI."
        ),
    )
    company_sizes: Annotated[
        tuple[CompanySize, ...],
        Field(
            max_length=len(CompanySize),
            description="Any combination of LinkedIn's eight visible company-size buckets.",
        ),
    ] = ()
    has_job_listings: bool = Field(
        default=False,
        description=("Require LinkedIn's visible 'Job listings on LinkedIn: Yes' Company filter."),
    )
    has_first_degree_connections: bool = Field(
        default=False,
        description="Require LinkedIn's visible 'Connections: 1st' Company filter.",
    )

    @model_validator(mode="after")
    def validate_filters(self) -> CompanySearchFilters:
        for label, values in (
            ("location", (*self.location_ids, *self.location_names)),
            ("industry", (*self.industry_ids, *self.industry_names)),
            ("company size", self.company_sizes),
        ):
            normalized = tuple(value.casefold() for value in values)
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{label} filters must not contain duplicates")
        if len(self.location_ids) + len(self.location_names) > 10:
            raise ValueError("At most 10 combined location IDs and names are allowed")
        if len(self.industry_ids) + len(self.industry_names) > 10:
            raise ValueError("At most 10 combined industry IDs and names are allowed")
        return self

    def has_constraints(self) -> bool:
        return any(
            (
                self.location_ids,
                self.location_names,
                self.industry_ids,
                self.industry_names,
                self.company_sizes,
                self.has_job_listings,
                self.has_first_degree_connections,
            )
        )


class CompanySearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for visible Company search.",
            ),
        ]
        | None
    ) = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> CompanySearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Company search requires query or at least one filter")
        return self


class CompanyGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    company_slug: CompanySlug


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


class InvitationListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    direction: InvitationDirection = InvitationDirection.RECEIVED
    invitation_filter: InvitationFilter | None = Field(
        default=None,
        description=(
            "Current visible LinkedIn invitation filter. Omit for the deduplicated union of "
            "every Received view or for Sent People."
        ),
    )

    @model_validator(mode="after")
    def validate_direction_filter(self) -> InvitationListInput:
        selected = self.resolved_filter
        if self.direction is InvitationDirection.SENT and selected is not InvitationFilter.PEOPLE:
            raise ValueError("Sent invitations support only the visible People filter")
        if self.direction is InvitationDirection.RECEIVED and selected is InvitationFilter.PEOPLE:
            raise ValueError("The People filter applies only to sent invitations")
        return self

    @property
    def resolved_filter(self) -> InvitationFilter:
        if self.invitation_filter is not None:
            return self.invitation_filter
        if self.direction is InvitationDirection.SENT:
            return InvitationFilter.PEOPLE
        return InvitationFilter.ALL


class ConnectionsListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED


class ConnectionsSearchInput(PaginatedInput):
    """Search established first-degree connections through LinkedIn People search."""

    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for connection search.",
            ),
        ]
        | None
    ) = None
    filters: ConnectionsSearchFilters = Field(
        default_factory=ConnectionsSearchFilters,
        description=(
            "Optional visible People filters. First-degree connection filtering is always "
            "enforced by the server and cannot be overridden."
        ),
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> ConnectionsSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Connection search requires query or at least one filter")
        return self

    def as_people_search_input(self) -> PeopleSearchInput:
        return PeopleSearchInput(
            context_id=self.context_id,
            request_id=self.request_id,
            query=self.query,
            filters=self.filters.as_people_search_filters(),
            page_size=self.page_size,
        )


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


class InvitationAcceptInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug


class InvitationIgnoreInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug


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


class JobSearchSort(StrEnum):
    MOST_RELEVANT = "most_relevant"
    MOST_RECENT = "most_recent"


class JobWorkplaceType(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    HYBRID = "hybrid"


class JobExperienceLevel(StrEnum):
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    ASSOCIATE = "associate"
    MID_SENIOR = "mid_senior"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


class JobEmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    VOLUNTEER = "volunteer"
    OTHER = "other"


class JobApplyMethod(StrEnum):
    EASY_APPLY = "easy_apply"
    EXTERNAL = "external"
    UNAVAILABLE = "unavailable"


class JobBenefit(StrEnum):
    MEDICAL_INSURANCE = "medical_insurance"
    VISION_INSURANCE = "vision_insurance"
    DENTAL_INSURANCE = "dental_insurance"
    RETIREMENT_401K = "retirement_401k"
    PENSION_PLAN = "pension_plan"
    PAID_MATERNITY_LEAVE = "paid_maternity_leave"
    PAID_PATERNITY_LEAVE = "paid_paternity_leave"
    COMMUTER_BENEFITS = "commuter_benefits"
    STUDENT_LOAN_ASSISTANCE = "student_loan_assistance"
    TUITION_ASSISTANCE = "tuition_assistance"
    DISABILITY_INSURANCE = "disability_insurance"


class JobCommitment(StrEnum):
    CAREER_GROWTH_AND_LEARNING = "career_growth_and_learning"
    DIVERSITY_EQUITY_AND_INCLUSION = "diversity_equity_and_inclusion"
    ENVIRONMENTAL_SUSTAINABILITY = "environmental_sustainability"
    SOCIAL_IMPACT = "social_impact"
    WORK_LIFE_BALANCE = "work_life_balance"


class JobSearchFilters(StrictModel):
    """Typed filters that map only to LinkedIn's visible Jobs search surface."""

    sort_by: JobSearchSort = Field(
        default=JobSearchSort.MOST_RELEVANT,
        description="Order results by LinkedIn relevance or visible posting recency.",
    )
    location_geo_id: (
        Annotated[
            str,
            StringConstraints(pattern=r"^[0-9]{3,30}$"),
        ]
        | None
    ) = Field(
        default=None,
        description="Optional LinkedIn numeric geography ID to disambiguate location.",
    )
    distance_miles: Literal[0, 5, 10, 25, 50, 100] | None = Field(
        default=None,
        description="Visible LinkedIn distance-radius choice for the selected geography.",
    )
    workplace_types: Annotated[tuple[JobWorkplaceType, ...], Field(max_length=3)] = Field(
        default=(),
        description="On-site, remote, and/or hybrid workplace choices.",
    )
    experience_levels: Annotated[tuple[JobExperienceLevel, ...], Field(max_length=6)] = Field(
        default=(),
        description="One or more LinkedIn experience-level choices.",
    )
    employment_types: Annotated[tuple[JobEmploymentType, ...], Field(max_length=7)] = Field(
        default=(),
        description="One or more LinkedIn employment-type choices.",
    )
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten additional exact LinkedIn location facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description="Additional visible location labels to resolve from current filter options.",
    )
    company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn company facet IDs.",
    )
    company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through LinkedIn's visible company filter.",
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industry names to resolve through LinkedIn's visible industry filter.",
    )
    job_function_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn job-function facet IDs.",
    )
    job_function_names: LinkedInFacetLabels = Field(
        default=(),
        description="Job-function names to resolve through LinkedIn's visible function filter.",
    )
    job_title_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn normalized job-title facet IDs.",
    )
    job_title_names: LinkedInFacetLabels = Field(
        default=(),
        description="Normalized job-title labels to resolve from current filter options.",
    )
    benefits: Annotated[tuple[JobBenefit, ...], Field(max_length=11)] = Field(
        default=(),
        description="One or more visible LinkedIn benefit choices.",
    )
    commitments: Annotated[tuple[JobCommitment, ...], Field(max_length=5)] = Field(
        default=(),
        description="One or more visible LinkedIn corporate-commitment choices.",
    )
    easy_apply_only: bool = Field(
        default=False,
        description="Return only jobs that use LinkedIn Easy Apply.",
    )
    has_verifications: bool = Field(
        default=False,
        description="Return only jobs carrying LinkedIn's available verification signals.",
    )
    under_10_applicants: bool = Field(
        default=False,
        description="Return only jobs shown by LinkedIn as having under ten applicants.",
    )
    in_your_network: bool = Field(
        default=False,
        description="Return only jobs at companies connected to the configured account's network.",
    )
    fair_chance_employer: bool = Field(
        default=False,
        description="Use LinkedIn's region/account-dependent Fair Chance Employer filter.",
    )

    @model_validator(mode="after")
    def reject_duplicate_values(self) -> JobSearchFilters:
        for field_name in (
            "workplace_types",
            "experience_levels",
            "employment_types",
            "location_ids",
            "location_names",
            "company_ids",
            "company_names",
            "industry_ids",
            "industry_names",
            "job_function_ids",
            "job_function_names",
            "job_title_ids",
            "job_title_names",
            "benefits",
            "commitments",
        ):
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            ("location_ids", "location_names"),
            ("company_ids", "company_names"),
            ("industry_ids", "industry_names"),
            ("job_function_ids", "job_function_names"),
            ("job_title_ids", "job_title_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        return self


class JobSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Keywords or a LinkedIn Boolean query using quotes, AND, OR, and NOT.",
            ),
        ]
        | None
    ) = None
    location: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible location text such as a city, region, country, or Worldwide.",
            ),
        ]
        | None
    ) = None
    freshness_hours: Literal[24, 168, 720] | None = Field(
        default=None,
        description=(
            "LinkedIn's visible Date posted choice: 24 hours, 168 hours (past week), "
            "720 hours (past month), or null for Any time."
        ),
    )
    filters: JobSearchFilters = Field(
        default_factory=JobSearchFilters,
        description="Optional structured LinkedIn Jobs filters.",
    )

    @model_validator(mode="after")
    def validate_distance_context(self) -> JobSearchInput:
        if (
            self.filters.distance_miles is not None
            and self.location is None
            and self.filters.location_geo_id is None
        ):
            raise ValueError("distance_miles requires location or filters.location_geo_id")
        return self


class JobDetailInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    job_id: JobId


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class PaginationMetadata(StrictModel):
    """Reader-facing state for one page of a process-local live scan."""

    scan_id: Identifier
    page_size: Annotated[int, Field(ge=1, le=100)]
    returned_count: Annotated[int, Field(ge=0, le=100)]
    cumulative_count: Annotated[int, Field(ge=0)]
    has_more: bool
    next_cursor: PaginationCursor | None = None
    cursor_expires_at: datetime | None = None
    truncated: bool = False
    consistency: Literal["live_deduplicated"] = "live_deduplicated"

    @model_validator(mode="after")
    def validate_cursor_state(self) -> PaginationMetadata:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match the presence of next_cursor")
        if self.has_more != (self.cursor_expires_at is not None):
            raise ValueError("has_more must match the cursor expiry")
        if self.returned_count > self.page_size:
            raise ValueError("returned_count cannot exceed page_size")
        return self


class EvidenceField(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]


class JobHiringTeamMember(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    connection_degree_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    role_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class JobSummary(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    easy_apply: bool = False
    verified: bool = False
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...] = ()


class JobSearchCoverage(StrictModel):
    query: str | None
    location: str | None
    freshness_hours: Literal[24, 168, 720] | None
    filters: JobSearchFilters = Field(default_factory=JobSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    advertised_result_count: Annotated[int, Field(ge=0)] | None = None
    advertised_result_count_is_lower_bound: bool = False
    captured_at: datetime


class JobSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    jobs: tuple[JobSummary, ...]
    coverage: JobSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class JobDetailObservation(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    employment_type: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    applicant_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    description_text: Annotated[str, Field(min_length=1)] | None = None
    apply_method: JobApplyMethod = JobApplyMethod.UNAVAILABLE
    easy_apply: bool | None = None
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    hiring_team: tuple[JobHiringTeamMember, ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...]
    captured_at: datetime


class JobDetailOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    job: JobDetailObservation
    sources: tuple[SourceReference, ...]


class PersonSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connection_degree: PersonConnectionDegree | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PeopleSearchCoverage(StrictModel):
    query: str | None
    filters: PeopleSearchFilters = Field(default_factory=PeopleSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unidentifiable_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Visible LinkedIn Member cards omitted because LinkedIn exposed no profile identity."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class PeopleSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    people: tuple[PersonSummary, ...]
    coverage: PeopleSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class PersonProfileLink(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=1_000)]
    url: HttpUrl


class PersonProfileSectionEntry(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    subtitle: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
    links: tuple[PersonProfileLink, ...] = ()


class PersonProfileSection(StrictModel):
    key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
    ]
    heading: Annotated[str, Field(min_length=1, max_length=500)]
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]
    entries: tuple[PersonProfileSectionEntry, ...] = ()


class PersonExperience(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization_url: HttpUrl | None = None
    employment_type: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    duration: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    is_current: bool | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]


class PersonEducation(StrictModel):
    school: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    school_url: HttpUrl | None = None
    degree: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    field_of_study: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]


class PersonProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


class PersonProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["profile", "section"]
    section_heading: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class PersonProfileCoverage(StrictModel):
    pages_visited: Annotated[int, Field(ge=1)]
    detail_pages_discovered: Annotated[int, Field(ge=0)]
    detail_pages_visited: Annotated[int, Field(ge=0)]
    detail_page_limit: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime
    requested_sections: tuple[PersonProfileSectionSelector, ...] = (
        PersonProfileSectionSelector.ALL,
    )
    returned_sections: tuple[str, ...] = ()
    detail_sections_discovered: tuple[str, ...] = ()
    detail_sections_visited: tuple[str, ...] = ()
    unavailable_sections: tuple[PersonProfileSectionSelector, ...] = ()
    truncated_sections: tuple[str, ...] = ()


class PersonProfileObservation(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    pronouns: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connection_degree: PersonConnectionDegree | None = None
    connection_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    current_company_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    education_summary_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    about: Annotated[str, Field(min_length=1)] | None = None
    experiences: tuple[PersonExperience, ...] = ()
    education: tuple[PersonEducation, ...] = ()
    sections: tuple[PersonProfileSection, ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[PersonProfileEvidence, ...]
    coverage: PersonProfileCoverage
    captured_at: datetime


class PeopleGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    person: PersonProfileObservation
    sources: tuple[SourceReference, ...]


class CompanySummary(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class CompanySearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class CompanySearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    companies: tuple[CompanySummary, ...]
    coverage: CompanySearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class CompanyProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


class CompanyProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["overview", "about"]
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class CompanyProfileCoverage(StrictModel):
    pages_visited: Literal[2] = 2
    returned_sections: tuple[Literal["overview"], Literal["about"]] = (
        "overview",
        "about",
    )
    captured_at: datetime


class CompanyProfileObservation(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    website_url: HttpUrl | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_size_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    headquarters: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization_type: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    founded_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    specialties: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[CompanyProfileEvidence, ...]
    coverage: CompanyProfileCoverage
    captured_at: datetime


class CompanyGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    company: CompanyProfileObservation
    sources: tuple[SourceReference, ...]


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


class InvitationEntity(StrictModel):
    entity_ref: Identifier
    entity_type: InvitationEntityType
    entity_url: HttpUrl | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    slug: (
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,199}$",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_known_entity_identity(self) -> InvitationEntity:
        if self.entity_type is not InvitationEntityType.OTHER and (
            self.entity_url is None or self.slug is None
        ):
            raise ValueError("Known invitation entities require a canonical URL and slug")
        return self


class InvitationEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl
    captured_at: datetime


class InvitationSummary(StrictModel):
    invitation_ref: Identifier
    direction: InvitationDirection
    invitation_type: InvitationType
    primary_entity: InvitationEntity
    inviter: InvitationEntity | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    context: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    sent_or_received_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    relationship_context: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    available_actions: tuple[InvitationAvailableAction, ...]
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[InvitationEvidence, ...]


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


class InvitationListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    invitations: tuple[InvitationSummary, ...]
    coverage: InvitationListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]

    @model_validator(mode="after")
    def validate_live_page(self) -> InvitationListOutput:
        returned = len(self.invitations)
        if self.coverage.result_count != returned or self.pagination.returned_count != returned:
            raise ValueError("Invitation page counts must match the returned invitations")
        if self.pagination.consistency != "live_deduplicated":
            raise ValueError("Invitation pagination must identify live-deduplicated consistency")
        if self.pagination.has_more and self.coverage.stop_reason not in {
            StopReason.RESULT_LIMIT,
            StopReason.SAFETY_BOUND,
        }:
            raise ValueError("Invitation continuation requires an honest non-terminal stop reason")
        if (
            not self.pagination.has_more
            and not self.pagination.truncated
            and self.coverage.stop_reason is not StopReason.VISIBLE_PAGE_COMPLETE
        ):
            raise ValueError("A complete invitation scan requires reconciled terminal coverage")
        references = [item.invitation_ref for item in self.invitations]
        if len(references) != len(set(references)):
            raise ValueError("Invitation pages cannot contain duplicate references")
        if any(item.direction is not self.coverage.direction for item in self.invitations):
            raise ValueError("Invitation page items must match the selected direction")
        return self


class ConnectionSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connected_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class ConnectionsListCoverage(StrictModel):
    sort_by: ConnectionsSortBy
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class ConnectionsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    connections: tuple[ConnectionSummary, ...]
    coverage: ConnectionsListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class ConnectionsSearchOutput(PeopleSearchOutput):
    """People-shaped results from LinkedIn's broad Connections search entry point."""


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


class CapabilityInfo(StrictModel):
    name: CapabilityName
    version: str
    effect: CapabilityEffect
    required_surfaces: tuple[LinkedInSurface, ...]
    enabled: Literal[True] = True


class CapabilityListOutput(StrictModel):
    capabilities: tuple[CapabilityInfo, ...]


class ServerStatusOutput(StrictModel):
    name: Literal["linkedin-mcp-server"] = "linkedin-mcp-server"
    version: str
    transport: Literal["stdio", "streamable-http"]
    operation_state: Literal["process_local"] = "process_local"
    runtime_model: Literal["shared_local"] = "shared_local"
    connected_clients: Annotated[int, Field(ge=0)] = 0
    queue_depth: Annotated[int, Field(ge=0)] = 0
    queued_clients: Annotated[int, Field(ge=0)] = 0
    active_browser_operation: bool = False
    active_capability: CapabilityName | None = None
    accepting_calls: bool = True


class SessionStatusOutput(StrictModel):
    account_id: Identifier
    profile_present: bool
    browser_setup_state: BrowserSetupState
    browser_started: bool
    authentication_state: SessionAuthenticationState
    automatic_login_enabled: bool
    login_browser_open: bool
    paused: bool
    pause_reason: str | None = None
    status_message: str | None = None
