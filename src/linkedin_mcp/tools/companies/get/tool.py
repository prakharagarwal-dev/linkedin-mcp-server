"""FastMCP definition for `linkedin.companies.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.companies.get.models.company_get_input import CompanyGetInput
from linkedin_mcp.tools.companies.get.models.company_get_output import CompanyGetOutput


def register(
    mcp: FastMCP[None],
    container: AppContainer,
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
        result = await tool_result(
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

    del _get_company
