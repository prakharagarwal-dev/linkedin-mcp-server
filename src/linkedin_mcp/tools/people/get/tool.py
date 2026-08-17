"""FastMCP definition for `linkedin.people.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.people.get.models import (
    PeopleGetInput,
    PeopleGetOutput,
    PersonProfileSectionSelector,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
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
        annotations=annotations,
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
        result = await tool_result(
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

    del _get_person
