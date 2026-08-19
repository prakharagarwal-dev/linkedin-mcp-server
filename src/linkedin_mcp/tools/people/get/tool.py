"""FastMCP definition for `linkedin.people.get`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.people.get.evidence import sources_from_person_profile
from linkedin_mcp.tools.people.get.models import (
    PROFILE_SLUG_PATTERN,
    PeopleGetInput,
    PeopleGetOutput,
    PersonProfileSectionSelector,
)
from linkedin_mcp.tools.people.get.page import PersonProfilePage

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


async def execute(request: PeopleGetInput, page: PersonProfilePage) -> PeopleGetOutput:
    person, captures = await page.read(request)
    return PeopleGetOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        person=person,
        sources=sources_from_person_profile(person, captures),
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: PersonProfilePage,
) -> None:
    @mcp.tool(
        name="linkedin.people.get",
        title="Read LinkedIn Member Profile",
        description=(
            "Read a visible LinkedIn member profile directly by validated public profile slug. "
            "Returns typed introduction, About, experience, education, every visible profile "
            "section owned by the member, full retained text, field evidence, and bounded "
            "section-page coverage."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
        request = PeopleGetInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
            sections=sections,
        )
        task = Task(
            name="linkedin.people.get",
            execute=lambda: execute(request, page),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn member profile complete")
        return result

    del _get_person
