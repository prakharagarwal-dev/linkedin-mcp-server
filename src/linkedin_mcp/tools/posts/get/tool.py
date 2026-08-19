"""FastMCP definition for `linkedin.posts.get`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.posts.get.evidence import source_from_post
from linkedin_mcp.tools.posts.get.models import PostGetInput, PostGetOutput
from linkedin_mcp.tools.posts.get.page import PostDetailPage

IdentifierArgument = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


async def tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = error if isinstance(error, LinkedInMCPError) else InternalServerError()
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


async def execute(request: PostGetInput, page: PostDetailPage) -> PostGetOutput:
    post = await page.read(request)
    return PostGetOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        post=post,
        sources=(source_from_post(post),),
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: PostDetailPage,
) -> None:
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
        request = PostGetInput(
            context_id=context_id,
            request_id=request_id,
            post_ref=post_ref,
        )
        task = Task(
            name="linkedin.posts.get",
            execute=lambda: execute(request, page),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn post detail complete")
        return result

    del _get_post
