"""FastMCP definition for `linkedin.companies.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.companies.get.evidence import sources_from_company_profile
from linkedin_mcp.tools.companies.get.models.company_get_input import CompanyGetInput
from linkedin_mcp.tools.companies.get.models.company_get_output import CompanyGetOutput
from linkedin_mcp.tools.companies.get.page import CompanyProfilePage


async def execute(request: CompanyGetInput, page: CompanyProfilePage) -> CompanyGetOutput:
    company, captures = await page.read(request)
    return CompanyGetOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        company=company,
        sources=sources_from_company_profile(company, captures),
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: CompanyProfilePage,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.companies.get",
        title="Read LinkedIn Company Overview and About",
        description=(
            "Read an exact visible LinkedIn Company by public slug. Always captures exactly the "
            "Company overview and About page, including identity, tagline, description, website, "
            "industry, company-size range, associated-member and follower counts, headquarters, "
            "organization type, founding year, specialties, and exact field evidence."
        ),
        annotations=annotations,
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
        request = CompanyGetInput(
            context_id=context_id,
            request_id=request_id,
            company_slug=company_slug,
        )
        task = Task(
            name="linkedin.companies.get",
            execute=lambda: execute(request, page),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn company profile complete")
        return result

    del _get_company
