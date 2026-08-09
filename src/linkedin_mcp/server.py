"""FastMCP transport adapter for the typed LinkedIn capability runtime."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp import __version__
from linkedin_mcp.application import bind_client_execution
from linkedin_mcp.application.executor import safe_capability_error
from linkedin_mcp.container import AppContainer
from linkedin_mcp.domain.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.domain.models import (
    ActionApprovalPreview,
    ActionExecuteInput,
    ActionExecuteOutput,
    ActionPrepareOutput,
    CapabilityListOutput,
    CommentAttachment,
    CommentSort,
    CompanyGetInput,
    CompanyGetOutput,
    CompanySearchFilters,
    CompanySearchInput,
    CompanySearchOutput,
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSearchFilters,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    ConnectionsSortBy,
    ConversationCategory,
    ConversationFilter,
    ConversationGetInput,
    ConversationGetOutput,
    ConversationSearchInput,
    ConversationSearchOutput,
    InvitationAcceptPrepareInput,
    InvitationDirection,
    InvitationFilter,
    InvitationIgnorePrepareInput,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendPrepareInput,
    JobDetailInput,
    JobDetailOutput,
    JobSearchFilters,
    JobSearchInput,
    JobSearchOutput,
    MessageFileInput,
    MessageGifInput,
    MessagePrepareInput,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleSearchFilters,
    PeopleSearchInput,
    PeopleSearchOutput,
    PersonProfileSectionSelector,
    PostAudience,
    PostCollaboratorInput,
    PostCommentControl,
    PostCommentPrepareInput,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreateContent,
    PostCreatePrepareInput,
    PostGetInput,
    PostGetOutput,
    PostGroupTarget,
    PostMentionInput,
    PostReactionPrepareInput,
    PostSearchFilters,
    PostSearchInput,
    PostSearchOutput,
    ReactionState,
    ServerStatusOutput,
    SessionStatusOutput,
)

IdentifierArgument = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
ActionIdArgument = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        description="Immutable action ID returned by the matching prepare tool.",
    ),
]
PayloadHashArgument = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="Exact payload hash returned by the matching prepare tool.",
    ),
]
PageSizeArgument = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Number of unique items to return in this page.",
    ),
]
CursorArgument = Annotated[
    str,
    Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Opaque continuation cursor returned as pagination.next_cursor by the preceding page."
        ),
    ),
]
LegacyPageSizeArgument = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Deprecated compatibility alias for page_size.",
    ),
]

EXECUTE_APPROVAL_POLICY_DESCRIPTION = (
    "Account-changing action. Invoke only when the MCP client's configured approval policy "
    "authorizes this exact execute tool. Interactive confirmation is the safe default; an "
    "explicit durable per-tool approval may authorize unattended execution. "
)


async def _tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = safe_capability_error(error)
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


def _effective_page_size(page_size: int, legacy_page_size: int | None) -> int:
    return legacy_page_size if legacy_page_size is not None else page_size


def create_mcp_server(
    container: AppContainer,
    *,
    manage_container_lifecycle: bool = True,
) -> FastMCP[None]:
    @asynccontextmanager
    async def lifespan(_: FastMCP[None]) -> AsyncGenerator[None]:
        if manage_container_lifecycle:
            await container.start()
        try:
            yield None
        finally:
            if manage_container_lifecycle:
                await container.close()

    mcp: FastMCP[None] = FastMCP(
        "linkedin-mcp-server",
        instructions=(
            "Prepare every account-changing action first. Then call the matching execute tool "
            "with action_id, payload_hash, and approval_preview copied exactly from prepare. The "
            "MCP client controls whether an execute tool uses interactive confirmation or an "
            "explicit durable per-tool approval; interactive confirmation is the safe default. "
            "Never treat chat text as a durable client approval policy, alter a preview, or call "
            "execute after an interactive denial. Use only registered typed LinkedIn "
            "capabilities. Cursors and prepared actions belong to the MCP session that created "
            "them. Operation state exists only for this server process; evidence is at "
            "linkedin://sources/{source_id}."
        ),
        json_response=True,
        stateless_http=False,
        host=container.settings.http_host,
        port=container.settings.http_port,
        log_level=container.settings.log_level,
        lifespan=lifespan,
    )
    # FastMCP does not currently forward a product version to its low-level server.
    mcp._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]

    local_read = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    linkedin_read = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
    messaging_read = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
    linkedin_prepare = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
    linkedin_write = ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=True,
    )

    @mcp.tool(
        name="linkedin.server.status",
        title="LinkedIn MCP Server Status",
        description="Return non-secret server configuration and readiness metadata.",
        annotations=local_read,
    )
    async def _server_status() -> ServerStatusOutput:
        return ServerStatusOutput(
            version=__version__,
            transport=container.settings.transport,
            connected_clients=container.clients.connected_count,
            queue_depth=container.worker.queue_depth,
            queued_clients=container.worker.queued_clients,
            active_browser_operation=container.worker.active,
            active_capability=container.worker.active_capability,
            accepting_calls=container.worker.accepting,
        )

    @mcp.tool(
        name="linkedin.capabilities.list",
        title="List LinkedIn Capabilities",
        description="List installed capabilities and whether runtime policy enables each one.",
        annotations=local_read,
    )
    async def _list_capabilities() -> CapabilityListOutput:
        return CapabilityListOutput(
            capabilities=tuple(
                descriptor.status(container.settings) for descriptor in container.registry.list()
            )
        )

    @mcp.tool(
        name="linkedin.session.status",
        title="LinkedIn Session Status",
        description="Return non-secret browser-session state for the configured account.",
        annotations=local_read,
    )
    async def _session_status() -> SessionStatusOutput:
        return SessionStatusOutput(
            account_id=container.settings.account_id,
            profile_present=container.browser.profile_present(),
            browser_setup_state=container.browser.browser_setup_state,
            browser_started=container.browser.started,
            authentication_state=container.browser.authentication_state,
            automatic_login_enabled=container.settings.auto_login_on_start,
            login_browser_open=container.browser.login_browser_open,
            paused=container.browser.paused,
            pause_reason=container.browser.pause_reason,
            status_message=container.browser.authentication_status_message,
        )

    @mcp.tool(
        name="linkedin.jobs.search",
        title="Search LinkedIn Jobs",
        description=(
            "Search current visible LinkedIn Jobs pages with optional keywords and typed "
            "location, Date posted, sorting, distance, workplace, experience, job type, "
            "company, industry, function, title, benefit, commitment, Easy Apply, "
            "verification, applicant-count, network, and Fair Chance filters. Hydrates "
            "LinkedIn's virtualized result cards and returns one deduplicated cursor page."
        ),
        annotations=linkedin_read,
    )
    async def _search_jobs(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=300,
                    description=(
                        "Optional keywords or a LinkedIn Boolean query using quotes, "
                        "AND, OR, and NOT."
                    ),
                ),
            ]
            | None
        ) = None,
        location: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=200,
                    description="City, region, country, postal code, or Worldwide.",
                ),
            ]
            | None
        ) = None,
        freshness_hours: Annotated[
            Literal[24, 168, 720] | None,
            Field(
                description=(
                    "Date posted: 24, 168 (past week), 720 (past month), or null for Any time."
                ),
            ),
        ] = None,
        filters: JobSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> JobSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn job search")
        result = await _tool_result(
            container.worker.search_jobs(
                JobSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    location=location,
                    freshness_hours=freshness_hours,
                    filters=filters or JobSearchFilters(),
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn job search complete")
        return result

    @mcp.tool(
        name="linkedin.jobs.get",
        title="Read LinkedIn Job",
        description=(
            "Read one current visible LinkedIn job by numeric ID, including its primary "
            "header metadata, application method, hiring-team identities, and fully expanded "
            "About the job description."
        ),
        annotations=linkedin_read,
    )
    async def _get_job(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        job_id: Annotated[str, Field(pattern=r"^[0-9]{5,30}$")],
        ctx: Context[Any, Any, Any],
    ) -> JobDetailOutput:
        await ctx.report_progress(0, 100, "Validating LinkedIn job target")
        result = await _tool_result(
            container.worker.get_job(
                JobDetailInput(
                    context_id=context_id,
                    request_id=request_id,
                    job_id=job_id,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn job detail complete")
        return result

    @mcp.tool(
        name="linkedin.people.search",
        title="Search LinkedIn People",
        description=(
            "Search visible LinkedIn People results using natural-language or Boolean keywords, "
            "connection degree, any/specific-title hiring, location, current/past company, "
            "connections-of, followers-of, school, industry, profile-language, service-category, "
            "and exact first-name, last-name, title, company, and school keyword filters. "
            "Returns one cursor page; name-to-ID resolution and traversal safety bounds remain "
            "private."
        ),
        annotations=linkedin_read,
    )
    async def _search_people(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean People-search keywords.",
                ),
            ]
            | None
        ) = None,
        title_keywords: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=300,
                    description=(
                        "Role/title terms appended to People-search keywords; this is not "
                        "represented as an exact-title facet by standard LinkedIn People search."
                    ),
                ),
            ]
            | None
        ) = None,
        filters: PeopleSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> PeopleSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn People search")
        result = await _tool_result(
            container.worker.search_people(
                PeopleSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    title_keywords=title_keywords,
                    filters=filters or PeopleSearchFilters(),
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn People search complete")
        return result

    @mcp.tool(
        name="linkedin.people.get",
        title="Read LinkedIn Member Profile",
        description=(
            "Read a visible LinkedIn member profile directly by validated public profile slug. "
            "Returns typed introduction, About, experience, education, every visible profile "
            "section owned by the member, full retained text, field evidence, and bounded "
            "section-page coverage."
        ),
        annotations=linkedin_read,
    )
    async def _get_person(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        profile_slug: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                pattern=PROFILE_SLUG_PATTERN,
                description="Public LinkedIn profile slug from linkedin.com/in/{profile_slug}.",
            ),
        ],
        ctx: Context[Any, Any, Any],
        sections: Annotated[
            tuple[PersonProfileSectionSelector, ...],
            Field(
                min_length=1,
                max_length=len(PersonProfileSectionSelector),
                description=(
                    "Visible profile sections to return. Use ['all'] for the complete "
                    "server-bounded read; the canonical overview is always captured for identity."
                ),
            ),
        ] = (PersonProfileSectionSelector.ALL,),
    ) -> PeopleGetOutput:
        await ctx.report_progress(0, 100, "Validating LinkedIn member target")
        result = await _tool_result(
            container.worker.get_person(
                PeopleGetInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    sections=sections,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn member profile complete")
        return result

    @mcp.tool(
        name="linkedin.companies.search",
        title="Search LinkedIn Companies",
        description=(
            "Search visible LinkedIn Company results using LinkedIn's complete current "
            "Company-search filter surface: keywords, headquarters location, industry, "
            "company-size range, visible job listings, and first-degree connection presence. "
            "Exact names are resolved only through visible filter controls; callers may "
            "alternatively provide stable facet IDs. Returns one cursor page."
        ),
        annotations=linkedin_read,
    )
    async def _search_companies(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean Company-search keywords.",
                ),
            ]
            | None
        ) = None,
        filters: CompanySearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> CompanySearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn Company search")
        result = await _tool_result(
            container.worker.search_companies(
                CompanySearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    filters=filters or CompanySearchFilters(),
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn Company search complete")
        return result

    @mcp.tool(
        name="linkedin.companies.get",
        title="Read LinkedIn Company Overview and About",
        description=(
            "Read an exact visible LinkedIn Company by public slug. Always captures exactly the "
            "Company overview and About page, including identity, tagline, description, website, "
            "industry, company-size range, associated-member and follower counts, headquarters, "
            "organization type, founding year, specialties, and exact field evidence."
        ),
        annotations=linkedin_read,
    )
    async def _get_company(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        company_slug: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$",
                description="Public LinkedIn company slug from /company/{company_slug}/.",
            ),
        ],
        ctx: Context[Any, Any, Any],
    ) -> CompanyGetOutput:
        await ctx.report_progress(0, 100, "Validating LinkedIn company target")
        result = await _tool_result(
            container.worker.get_company(
                CompanyGetInput(
                    context_id=context_id,
                    request_id=request_id,
                    company_slug=company_slug,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn company profile complete")
        return result

    @mcp.tool(
        name="linkedin.posts.search",
        title="Search LinkedIn Posts",
        description=(
            "Search visible LinkedIn content using keywords plus sort, date, content type, "
            "From-member/company, posted-by relationship, mentioning-member/company, "
            "author-industry/company, and Author Keywords filters. Content type follows "
            "LinkedIn's current single-choice Videos, Images, Job posts, Live videos, or "
            "Documents control. Names resolve only through exact visible choices. Returns "
            "one cursor page while browser traversal remains privately bounded."
        ),
        annotations=linkedin_read,
    )
    async def _search_posts(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean post-search keywords.",
                ),
            ]
            | None
        ) = None,
        filters: PostSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> PostSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn post search")
        result = await _tool_result(
            container.worker.search_posts(
                PostSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    filters=filters or PostSearchFilters(),
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn post search complete")
        return result

    @mcp.tool(
        name="linkedin.posts.get",
        title="Read LinkedIn Post",
        description=(
            "Read one exact visible LinkedIn post by stable activity, share, or ugc-post "
            "reference. Returns typed author/header data, fully expanded text, scoped links, "
            "mentions and hashtags, current image/video/document/link-card/poll details, "
            "viewer reaction and engagement counts, visibility, timestamps, immutable "
            "field evidence, and bounded completeness coverage. Reposts retain the wrapper "
            "and read the visibly linked original as one additional bounded page."
        ),
        annotations=linkedin_read,
    )
    async def _get_post(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(
                pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$",
                description="Stable post reference returned by LinkedIn post search.",
            ),
        ],
        ctx: Context[Any, Any, Any],
    ) -> PostGetOutput:
        await ctx.report_progress(0, 100, "Validating LinkedIn post target")
        result = await _tool_result(
            container.worker.get_post(
                PostGetInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn post detail complete")
        return result

    @mcp.tool(
        name="linkedin.posts.comments.list",
        title="Read LinkedIn Post Discussion",
        description=(
            "Read one cursor page of visible top-level comments and bounded nested replies, "
            "with relevant/recent ordering, stable comment references, exact author identities, "
            "visible text, timestamps, reaction/reply counts, and truncation coverage."
        ),
        annotations=linkedin_read,
    )
    async def _list_post_comments(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        ctx: Context[Any, Any, Any],
        sort_by: CommentSort = CommentSort.MOST_RELEVANT,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25,
        max_comments: LegacyPageSizeArgument | None = None,
    ) -> PostCommentsListOutput:
        await ctx.report_progress(0, 100, "Opening visible LinkedIn post discussion")
        result = await _tool_result(
            container.worker.list_post_comments(
                PostCommentsListInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    sort_by=sort_by,
                    page_size=_effective_page_size(page_size, max_comments),
                    cursor=cursor,
                    max_replies_per_comment=max_replies_per_comment,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn post discussion complete")
        return result

    @mcp.tool(
        name="linkedin.posts.create.prepare",
        title="Prepare Personal LinkedIn Post",
        description=(
            "Inspect the active personal member composer and prepare one immutable post. "
            "Supports typed text/link, up to 20 edited photos with alt text and member/company "
            "tags, video with thumbnail/captions, document, poll, celebration, event, existing-"
            "job hiring, and expert-request content. Exact audience/group, comment control, "
            "brand partnership, eligible collaborators, mentions, local asset hashes, and "
            "optional schedule are captured. The content discriminator is mode, not kind. "
            "This tool never publishes and never publishes as a company Page."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_post_create(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        content: PostCreateContent,
        ctx: Context[Any, Any, Any],
        audience: PostAudience = PostAudience.ANYONE,
        group_target: PostGroupTarget | None = None,
        comment_control: PostCommentControl = PostCommentControl.ANYONE,
        brand_partnership: bool = False,
        collaborators: Annotated[
            tuple[PostCollaboratorInput, ...],
            Field(max_length=5),
        ] = (),
        scheduled_at: datetime | None = None,
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Inspecting personal LinkedIn post composer")
        result = await _tool_result(
            container.worker.prepare_post_create(
                PostCreatePrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    content=content,
                    audience=audience,
                    group_target=group_target,
                    comment_control=comment_control,
                    brand_partnership=brand_partnership,
                    collaborators=collaborators,
                    scheduled_at=scheduled_at,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable personal-post draft prepared")
        return result

    @mcp.tool(
        name="linkedin.posts.create.execute",
        title="Publish or Schedule Prepared Personal LinkedIn Post",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Publish or schedule exactly one immutable "
            "personal-post draft after the server verifies the exact preview, payload and asset "
            "hashes, actor, expiry, options, and global idempotency key. An interrupted final "
            "action is never retried automatically."
        ),
        annotations=linkedin_write,
    )
    async def _execute_post_create(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized personal-post action")
        result = await _tool_result(
            container.worker.execute_post_create(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Personal-post action reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.posts.comment.prepare",
        title="Prepare LinkedIn Comment or Reply",
        description=(
            "Inspect one exact visible post or parent comment and prepare an immutable personal-"
            "member comment or reply. Supports text, links, emoji, exact member/company mentions, "
            "one local hash-locked photo, or one exact visible GIF result. This tool never submits."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_post_comment(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        ctx: Context[Any, Any, Any],
        parent_comment_ref: (
            Annotated[
                str,
                Field(
                    pattern=(
                        r"^comment:(?:activity|share|ugc-post):"
                        r"[0-9]{5,30}:[0-9]{1,30}$"
                    )
                ),
            ]
            | None
        ) = None,
        text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None,
        mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = (),
        attachment: CommentAttachment | None = None,
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Inspecting exact LinkedIn discussion target")
        result = await _tool_result(
            container.worker.prepare_post_comment(
                PostCommentPrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    parent_comment_ref=parent_comment_ref,
                    text=text,
                    mentions=mentions,
                    attachment=attachment,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable comment or reply draft prepared")
        return result

    @mcp.tool(
        name="linkedin.posts.comment.execute",
        title="Publish Prepared LinkedIn Comment or Reply",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Submit exactly one immutable personal-member "
            "comment or reply after the server verifies the preview, actor, target author, exact "
            "parent, payload, local asset hash, expiry, and idempotency."
        ),
        annotations=linkedin_write,
    )
    async def _execute_post_comment(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized LinkedIn comment action")
        result = await _tool_result(
            container.worker.execute_post_comment(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Comment action reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.posts.reaction.prepare",
        title="Prepare LinkedIn Post or Comment Reaction",
        description=(
            "Inspect the exact current reaction state on one visible post or comment and prepare "
            "an immutable target state: none, like, celebrate, support, love, insightful, or "
            "funny. This tool never changes the reaction."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_post_reaction(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        desired_reaction: ReactionState,
        ctx: Context[Any, Any, Any],
        comment_ref: (
            Annotated[
                str,
                Field(
                    pattern=(
                        r"^comment:(?:activity|share|ugc-post):"
                        r"[0-9]{5,30}:[0-9]{1,30}$"
                    )
                ),
            ]
            | None
        ) = None,
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Inspecting exact LinkedIn reaction state")
        result = await _tool_result(
            container.worker.prepare_post_reaction(
                PostReactionPrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    comment_ref=comment_ref,
                    desired_reaction=desired_reaction,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable reaction-state draft prepared")
        return result

    @mcp.tool(
        name="linkedin.posts.reaction.execute",
        title="Apply Prepared LinkedIn Post or Comment Reaction",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Set, change, remove, or safely no-op one "
            "prepared exact reaction state after the server verifies the preview, actor, target "
            "author, prior state, expiry, and idempotency."
        ),
        annotations=linkedin_write,
    )
    async def _execute_post_reaction(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized LinkedIn reaction action")
        result = await _tool_result(
            container.worker.execute_post_reaction(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Reaction action reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.invitations.list",
        title="List LinkedIn Invitations",
        description=(
            "Read one live cursor page from the current received or sent invitation inventory, "
            "including the deduplicated union of LinkedIn's current Focused, Other, Verified, "
            "Mutual Connections, Your Company, and Your School received views when "
            "invitation_filter is all. Continuations rescan a bounded live prefix, suppress "
            "stable identities already returned, and claim completion only after the selected "
            "visible counts reconcile."
        ),
        annotations=linkedin_read,
    )
    async def _list_invitations(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        direction: InvitationDirection = InvitationDirection.RECEIVED,
        invitation_filter: InvitationFilter | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> InvitationListOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn invitation read")

        async def report_progress(current: int, total: int, message: str) -> None:
            ratio = 1.0 if total == 0 else min(1.0, current / total)
            await ctx.report_progress(5 + round(90 * ratio), 100, message)

        result = await _tool_result(
            container.worker.list_invitations(
                InvitationListInput(
                    context_id=context_id,
                    request_id=request_id,
                    direction=direction,
                    invitation_filter=invitation_filter,
                    page_size=page_size,
                    cursor=cursor,
                ),
                progress=report_progress,
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn invitation read complete")
        return result

    @mcp.tool(
        name="linkedin.connections.list",
        title="List LinkedIn Connections",
        description=(
            "List one cursor page of the configured account's visible first-degree connection "
            "inventory in LinkedIn's selected visible sort order. This tool does not search."
        ),
        annotations=linkedin_read,
    )
    async def _list_connections(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> ConnectionsListOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn connections read")
        result = await _tool_result(
            container.worker.list_connections(
                ConnectionsListInput(
                    context_id=context_id,
                    request_id=request_id,
                    sort_by=sort_by,
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn connections read complete")
        return result

    @mcp.tool(
        name="linkedin.connections.search",
        title="Search LinkedIn Connections",
        description=(
            "Search only the configured account's established first-degree connections through "
            "LinkedIn's current People surface. The server always enforces first degree. "
            "Supports the remaining current visible People filters: any/specific-title hiring, "
            "locations, current/past companies, connections-of, followers-of, schools, "
            "industries, profile languages, service categories, and first-name, last-name, "
            "title, company, and school keywords. Use linkedin.people.search for broader "
            "second-, third-plus-, or mixed-degree discovery."
        ),
        annotations=linkedin_read,
    )
    async def _search_connections(  # pyright: ignore[reportUnusedFunction]
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean first-degree connection keywords.",
                ),
            ]
            | None
        ) = None,
        title_keywords: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=300,
                    description=("Role/title terms appended to the first-degree connection query."),
                ),
            ]
            | None
        ) = None,
        filters: ConnectionsSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> ConnectionsSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn connection search")
        result = await _tool_result(
            container.worker.search_connections(
                ConnectionsSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    title_keywords=title_keywords,
                    filters=filters or ConnectionsSearchFilters(),
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn connection search complete")
        return result

    @mcp.tool(
        name="linkedin.invitations.send.prepare",
        title="Prepare LinkedIn Connection Invitation",
        description=(
            "Inspect one exact visible profile and create an immutable invitation draft. "
            "This does not send the invitation. An optional personalized note is limited "
            "to 200 characters and returned with the exact client-approval preview."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_send(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        profile_slug: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                pattern=PROFILE_SLUG_PATTERN,
            ),
        ],
        ctx: Context[Any, Any, Any],
        note: Annotated[str, Field(min_length=1, max_length=200)] | None = None,
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Checking visible connection eligibility")
        result = await _tool_result(
            container.worker.prepare_invitation_send(
                InvitationSendPrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    note=note,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable invitation draft prepared")
        return result

    @mcp.tool(
        name="linkedin.invitations.send.execute",
        title="Send Prepared LinkedIn Connection Invitation",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Send exactly one immutable invitation draft "
            "after the server verifies the exact preview, payload hash, draft expiry, idempotency "
            "key, target identity, and actionable Send control. After the click, one fresh exact-"
            "profile read is the complete postcondition: Pending is verified success and Connect "
            "is verified LinkedIn failure. An unreadable or ambiguous fresh profile remains "
            "uncertain."
        ),
        annotations=linkedin_write,
    )
    async def _execute_send(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized invitation action")
        result = await _tool_result(
            container.worker.execute_invitation_send(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Invitation execution reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.invitations.accept.prepare",
        title="Prepare LinkedIn Connection Acceptance",
        description=(
            "Revalidate the exact member profile's paired visible incoming-request controls "
            "and create an immutable acceptance draft. This does not accept the request."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_accept(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        profile_slug: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                pattern=PROFILE_SLUG_PATTERN,
            ),
        ],
        ctx: Context[Any, Any, Any],
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Checking exact incoming connection request")
        result = await _tool_result(
            container.worker.prepare_invitation_accept(
                InvitationAcceptPrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable acceptance draft prepared")
        return result

    @mcp.tool(
        name="linkedin.invitations.accept.execute",
        title="Accept Prepared LinkedIn Connection Invitation",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Accept exactly one immutable incoming-request "
            "draft after the server verifies the preview, payload hash, draft expiry, "
            "idempotency, exact profile identity, and current request controls; then verify those "
            "controls are absent and the exact profile visibly shows a first-degree connection."
        ),
        annotations=linkedin_write,
    )
    async def _execute_accept(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized acceptance action")
        result = await _tool_result(
            container.worker.execute_invitation_accept(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Acceptance execution reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.invitations.ignore.prepare",
        title="Prepare Ignoring a LinkedIn Connection Request",
        description=(
            "Revalidate the exact member profile's current visible incoming connection request "
            "and create an immutable ignore draft. This does not ignore the request."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_ignore(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        profile_slug: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                pattern=PROFILE_SLUG_PATTERN,
            ),
        ],
        ctx: Context[Any, Any, Any],
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Checking exact incoming connection request")
        result = await _tool_result(
            container.worker.prepare_invitation_ignore(
                InvitationIgnorePrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable ignore draft prepared")
        return result

    @mcp.tool(
        name="linkedin.invitations.ignore.execute",
        title="Ignore Prepared LinkedIn Connection Request",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Ignore exactly one immutable incoming-request "
            "draft after the server verifies the preview, payload hash, draft expiry, "
            "idempotency, exact profile identity, and current request controls; then verify those "
            "controls are absent on a fresh exact-profile read."
        ),
        annotations=linkedin_write,
    )
    async def _execute_ignore(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized ignore action")
        result = await _tool_result(
            container.worker.execute_invitation_ignore(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Ignore execution reached a terminal outcome")
        return result

    @mcp.tool(
        name="linkedin.messaging.search",
        title="Search LinkedIn Messages",
        description=(
            "Search the current desktop inbox by recipient or message keywords, optionally "
            "within Focused, Other, Archived, or Spam and exactly one of Jobs, Unread, "
            "Connections, InMail, or Starred. At least one search criterion is required. "
            "Results are cursor-paginated current conversation cards."
        ),
        annotations=linkedin_read,
    )
    async def _search_messages(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: Annotated[str, Field(min_length=1, max_length=500)] | None = None,
        category: ConversationCategory | None = None,
        filter: ConversationFilter | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_results: LegacyPageSizeArgument | None = None,
    ) -> ConversationSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn inbox read")
        result = await _tool_result(
            container.worker.search_messages(
                ConversationSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    category=category,
                    filter=filter,
                    page_size=_effective_page_size(page_size, max_results),
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn inbox read complete")
        return result

    @mcp.tool(
        name="linkedin.messaging.conversation.get",
        title="Read LinkedIn Conversation",
        description=(
            "Traverse LinkedIn's reverse-virtualized visible history and read both incoming "
            "and outgoing messages, attachments, replies, edits, and reaction summaries "
            "by exact profile slug, visible conversation ID, or a conversation_ref returned "
            "by messaging.search. Returns explicit history completeness and truncation "
            "evidence. Opening a conversation may cause LinkedIn to mark it seen."
        ),
        annotations=messaging_read,
    )
    async def _get_conversation(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        profile_slug: (
            Annotated[
                str,
                Field(
                    min_length=3,
                    max_length=200,
                    pattern=PROFILE_SLUG_PATTERN,
                ),
            ]
            | None
        ) = None,
        conversation_id: (
            Annotated[
                str,
                Field(min_length=3, max_length=500, pattern=r"^[A-Za-z0-9_%=-]+$"),
            ]
            | None
        ) = None,
        conversation_ref: (
            Annotated[str, Field(pattern=r"^conversation:[0-9a-f]{24}$")] | None
        ) = None,
        max_messages: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> ConversationGetOutput:
        await ctx.report_progress(0, 100, "Opening visible LinkedIn conversation")
        result = await _tool_result(
            container.worker.get_conversation(
                ConversationGetInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    conversation_id=conversation_id,
                    conversation_ref=conversation_ref,
                    max_messages=max_messages,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn conversation read complete")
        return result

    @mcp.tool(
        name="linkedin.messaging.message.prepare",
        title="Prepare LinkedIn Message",
        description=(
            "Open one visible one-to-one standard conversation, using the exact profile's "
            "Message button for profile targets and accepting its recipient-bound compact "
            "pane or following its exact visible Messaging href in the same operation page, "
            "then create an immutable message draft containing exact text/emoji, hash-locked "
            "current desktop file attachments, one exact KLIPY GIF title, and optionally an "
            "exact reply-to message_ref. This does not send the "
            "message. Group chats, message requests, and paid InMail are excluded."
        ),
        annotations=linkedin_prepare,
    )
    async def _prepare_message(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        message: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None,
        attachments: Annotated[tuple[MessageFileInput, ...], Field(max_length=20)] = (),
        gif: MessageGifInput | None = None,
        reply_to_message_ref: (
            Annotated[str, Field(pattern=r"^message:[0-9a-f]{24}$")] | None
        ) = None,
        profile_slug: (
            Annotated[
                str,
                Field(
                    min_length=3,
                    max_length=200,
                    pattern=PROFILE_SLUG_PATTERN,
                ),
            ]
            | None
        ) = None,
        conversation_id: (
            Annotated[
                str,
                Field(min_length=3, max_length=500, pattern=r"^[A-Za-z0-9_%=-]+$"),
            ]
            | None
        ) = None,
        conversation_ref: (
            Annotated[str, Field(pattern=r"^conversation:[0-9a-f]{24}$")] | None
        ) = None,
    ) -> ActionPrepareOutput:
        await ctx.report_progress(0, 100, "Checking visible message target")
        result = await _tool_result(
            container.worker.prepare_message(
                MessagePrepareInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    conversation_id=conversation_id,
                    conversation_ref=conversation_ref,
                    message=message,
                    attachments=attachments,
                    gif=gif,
                    reply_to_message_ref=reply_to_message_ref,
                )
            )
        )
        await ctx.report_progress(100, 100, "Immutable message draft prepared")
        return result

    @mcp.tool(
        name="linkedin.messaging.message.execute",
        title="Send Prepared LinkedIn Message",
        description=(
            f"{EXECUTE_APPROVAL_POLICY_DESCRIPTION}Send exactly one immutable text/file message "
            "or immediate-send GIF, optionally as an exact visible reply, after the server "
            "verifies the preview, payload and asset hashes, draft expiry, recipient, idempotency, "
            "and exact visible outgoing postcondition in the same conversation surface."
        ),
        annotations=linkedin_write,
    )
    async def _execute_message(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        action_id: ActionIdArgument,
        payload_hash: PayloadHashArgument,
        approval_preview: ActionApprovalPreview,
        idempotency_key: IdentifierArgument,
        ctx: Context[Any, Any, Any],
    ) -> ActionExecuteOutput:
        await ctx.report_progress(0, 100, "Validating authorized message action")
        result = await _tool_result(
            container.worker.execute_message(
                ActionExecuteInput(
                    context_id=context_id,
                    request_id=request_id,
                    action_id=action_id,
                    payload_hash=payload_hash,
                    approval_preview=approval_preview,
                    idempotency_key=idempotency_key,
                )
            )
        )
        await ctx.report_progress(100, 100, "Message execution reached a terminal outcome")
        return result

    @mcp.resource(
        "linkedin://sources/{source_id}",
        name="LinkedIn Captured Source",
        description="Read immutable captured LinkedIn evidence from this server process.",
        mime_type="application/json",
    )
    async def _captured_source(source_id: str) -> str:
        try:
            source = await container.repository.get_source(
                account_id=container.settings.account_id,
                source_id=source_id,
            )
        except Exception as error:
            raise ResourceError("The captured source could not be loaded.") from error
        if source is None:
            raise ResourceError("The captured source does not exist for this account.")
        return source.model_dump_json(indent=2)

    registered_handlers = (
        _server_status,
        _list_capabilities,
        _session_status,
        _search_jobs,
        _get_job,
        _search_people,
        _get_person,
        _search_companies,
        _get_company,
        _search_posts,
        _get_post,
        _list_post_comments,
        _prepare_post_create,
        _execute_post_create,
        _prepare_post_comment,
        _execute_post_comment,
        _prepare_post_reaction,
        _execute_post_reaction,
        _list_invitations,
        _list_connections,
        _search_connections,
        _prepare_send,
        _execute_send,
        _prepare_accept,
        _execute_accept,
        _prepare_ignore,
        _execute_ignore,
        _search_messages,
        _get_conversation,
        _prepare_message,
        _execute_message,
        _captured_source,
    )
    del registered_handlers
    _install_client_execution_scope(mcp, container)
    return mcp


def _install_client_execution_scope(mcp: FastMCP[None], container: AppContainer) -> None:
    """Bind every protocol request to an opaque identity owned by its MCP session."""

    low_level = mcp._mcp_server  # pyright: ignore[reportPrivateUsage]
    for request_type, handler in tuple(low_level.request_handlers.items()):

        async def scoped(request: Any, *, _handler: Any = handler) -> Any:
            session = low_level.request_context.session
            client_id = container.clients.resolve(session)
            with bind_client_execution(client_id):
                return await _handler(request)

        low_level.request_handlers[request_type] = scoped
