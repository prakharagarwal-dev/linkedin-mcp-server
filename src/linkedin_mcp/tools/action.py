"""Single-attempt execution shared by account-changing tools."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.tools._shared.action_evidence import source_from_action_execution
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionPageResult,
    ActionPayload,
    ActionResult,
    ActionType,
)

logger = structlog.get_logger(__name__)


async def execute_action(
    *,
    task_name: str,
    context_id: str,
    request_id: str,
    action_type: ActionType,
    inspect: Callable[[], Awaitable[ActionInspection]],
    perform: Callable[[ActionCommand], Awaitable[ActionPageResult]],
    payload: ActionPayload | None = None,
    payload_factory: Callable[[ActionInspection], ActionPayload] | None = None,
) -> ActionOutput:
    """Inspect, perform once, and report the visible outcome of one write task."""

    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await inspect()
    resolved_payload = payload_factory(inspection) if payload_factory is not None else payload
    if resolved_payload is None:
        raise RuntimeError("Action inspection produced no typed payload.")
    command = ActionCommand(
        action_type=action_type,
        target=inspection.target,
        payload=resolved_payload,
    )
    try:
        page_result = await perform(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name=task_name,
            error_type=type(error).__name__,
        )
        result = ActionResult(
            action_type=action_type,
            outcome=ActionOutcome.UNCERTAIN,
            performed=None,
            final_state="unknown_after_interruption",
            detail=(
                "Execution stopped without a verified visible outcome; operator review is required."
            ),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        return ActionOutput(
            context_id=context_id,
            request_id=request_id,
            result=result,
            sources=(),
        )

    result = ActionResult(
        action_type=action_type,
        outcome=page_result.outcome,
        performed=page_result.performed,
        final_state=page_result.final_state,
        detail=page_result.detail,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    source = source_from_action_execution(page_result, execution_id=execution_id)
    return ActionOutput(
        context_id=context_id,
        request_id=request_id,
        result=result,
        sources=(source,),
    )
