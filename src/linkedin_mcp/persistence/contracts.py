"""Process-local operation contracts for capability execution and evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from linkedin_mcp.domain.models import (
    ActionApprovalPreview,
    ActionDraft,
    ActionOutcome,
    ActionType,
    CapabilityName,
    CapturedSource,
)


class CallStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CallStart:
    call_id: str
    created: bool
    status: CallStatus
    output: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


class AttemptStatus(StrEnum):
    EXECUTING = "executing"
    VERIFIED = "verified"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class ActionAttemptStart:
    attempt_id: str
    action: ActionDraft
    created: bool
    status: AttemptStatus
    started_at: datetime
    result: dict[str, object] | None = None
    sources: tuple[CapturedSource, ...] = ()


class Repository(Protocol):
    async def begin_call(
        self,
        *,
        account_id: str,
        context_id: str,
        request_id: str,
        capability_name: CapabilityName,
        input_fingerprint: str,
        input_value: dict[str, object],
    ) -> CallStart: ...

    async def complete_call(
        self,
        *,
        call_id: str,
        output: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None: ...

    async def complete_preparation_call(
        self,
        *,
        call_id: str,
        draft: ActionDraft,
        output: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None: ...

    async def fail_call(
        self,
        *,
        call_id: str,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def get_source(self, *, account_id: str, source_id: str) -> CapturedSource | None: ...

    async def get_action(self, *, account_id: str, action_id: str) -> ActionDraft | None: ...

    async def begin_action_attempt(
        self,
        *,
        account_id: str,
        action_id: str,
        expected_action_type: ActionType,
        expected_payload_hash: str,
        approval_preview: ActionApprovalPreview,
        idempotency_key: str,
    ) -> ActionAttemptStart: ...

    async def complete_action_attempt(
        self,
        *,
        account_id: str,
        context_id: str,
        attempt_id: str,
        outcome: ActionOutcome,
        result: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None: ...

    async def close(self) -> None: ...
