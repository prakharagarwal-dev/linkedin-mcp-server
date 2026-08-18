"""FastMCP definition for `linkedin.jobs.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.execution import Task
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.jobs.get.evidence import source_from_job_detail
from linkedin_mcp.tools.jobs.get.models.job_detail_input import JobDetailInput
from linkedin_mcp.tools.jobs.get.models.job_detail_output import JobDetailOutput
from linkedin_mcp.tools.jobs.get.page import JobDetailPage


async def execute(request: JobDetailInput, page: JobDetailPage) -> JobDetailOutput:
    job = await page.read(request)
    return JobDetailOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        job=job,
        sources=(source_from_job_detail(job),),
    )


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.jobs.get",
        title="Read LinkedIn Job",
        description=(
            "Read one current visible LinkedIn job by numeric ID, including its primary "
            "header metadata, application method, hiring-team identities, and fully expanded "
            "About the job description."
        ),
        annotations=annotations,
    )
    async def _get_job(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        job_id: Annotated[str, Field(pattern=r"^[0-9]{5,30}$")],
        ctx: Context[Any, Any, Any],
    ) -> JobDetailOutput:
        await ctx.report_progress(0, 100, "Validating LinkedIn job target")
        request = JobDetailInput(
            context_id=context_id,
            request_id=request_id,
            job_id=job_id,
        )
        task = Task(
            name="linkedin.jobs.get",
            execute=lambda: execute(request, container.job_detail),
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn job detail complete")
        return result

    del _get_job
