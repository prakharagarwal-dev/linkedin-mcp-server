"""Shared execution mechanics used by feature-owned LinkedIn operations."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

import structlog

from linkedin_mcp.app.pagination import PaginationLease, PaginationManager, request_binding
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.linkedin.action_evidence import source_from_action_execution
from linkedin_mcp.linkedin.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionPageResult,
    ActionPayload,
    ActionResult,
    ActionType,
)
from linkedin_mcp.linkedin.common import CapabilityName, PaginatedInput
from linkedin_mcp.mcp.context import current_execution_context

logger = structlog.get_logger(__name__)


class ActionRequest(Protocol):
    context_id: str
    request_id: str


class OperationSupport:
    """Shared pagination and single-attempt action execution for feature operations."""

    _settings: Settings
    _pagination: PaginationManager

    async def _run_action(
        self,
        *,
        capability_name: CapabilityName,
        request: ActionRequest,
        action_type: ActionType,
        inspect: Callable[[], Awaitable[ActionInspection]],
        perform: Callable[[ActionCommand], Awaitable[ActionPageResult]],
        payload: ActionPayload | None = None,
        payload_factory: Callable[[ActionInspection], ActionPayload] | None = None,
    ) -> ActionOutput:
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
                capability_name=capability_name.value,
                error_type=type(error).__name__,
            )
            result = ActionResult(
                action_type=action_type,
                outcome=ActionOutcome.UNCERTAIN,
                performed=None,
                final_state="unknown_after_interruption",
                detail=(
                    "Execution stopped without a verified visible outcome; "
                    "operator review is required."
                ),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            return ActionOutput(
                context_id=request.context_id,
                request_id=request.request_id,
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
            context_id=request.context_id,
            request_id=request.request_id,
            result=result,
            sources=(source,),
        )

    async def _pagination_lease(
        self,
        capability_name: CapabilityName,
        request: PaginatedInput,
    ) -> PaginationLease:
        execution = current_execution_context()
        lease = execution.pagination_lease
        if lease is None:
            return await self._pagination.acquire(
                account_id=self._settings.account_id,
                client_id=execution.client_id,
                capability_name=capability_name,
                request=request,
            )
        if (
            lease.account_id != self._settings.account_id
            or lease.client_id != execution.client_id
            or lease.capability_name is not capability_name
            or lease.binding != request_binding(capability_name, request)
        ):
            raise RuntimeError("The queued pagination lease does not match this atomic call.")
        return lease
