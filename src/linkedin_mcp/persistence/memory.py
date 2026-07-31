"""Process-local calls, evidence, action drafts, and attempts."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from linkedin_mcp.domain.models import (
    ActionApprovalPreview,
    ActionDraft,
    ActionOutcome,
    ActionStatus,
    ActionType,
    CapabilityName,
    CapturedSource,
    action_approval_preview,
)
from linkedin_mcp.errors import (
    AuthorizationDeniedError,
    IdempotencyConflictError,
    InvalidTargetError,
)
from linkedin_mcp.persistence.contracts import (
    ActionAttemptStart,
    AttemptStatus,
    CallStart,
    CallStatus,
    Repository,
)


@dataclass(slots=True)
class _Call:
    call_id: str
    account_id: str
    input_fingerprint: str
    status: CallStatus = CallStatus.STARTED
    output: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class _Action:
    account_id: str
    draft: ActionDraft


@dataclass(slots=True)
class _Attempt:
    attempt_id: str
    account_id: str
    action_id: str
    idempotency_key: str
    status: AttemptStatus
    started_at: datetime
    result: dict[str, object] | None = None
    sources: tuple[CapturedSource, ...] = ()


class MemoryRepository(Repository):
    """Bound all operation state to one MCP process lifetime."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._calls_by_key: dict[tuple[str, CapabilityName, str], _Call] = {}
        self._calls_by_id: dict[str, _Call] = {}
        self._sources: dict[tuple[str, str], CapturedSource] = {}
        self._actions: dict[str, _Action] = {}
        self._attempts_by_key: dict[str, _Attempt] = {}
        self._attempts_by_id: dict[str, _Attempt] = {}

    async def begin_call(
        self,
        *,
        account_id: str,
        context_id: str,
        request_id: str,
        capability_name: CapabilityName,
        input_fingerprint: str,
        input_value: dict[str, object],
    ) -> CallStart:
        del context_id, input_value
        key = (account_id, capability_name, request_id)
        async with self._lock:
            existing = self._calls_by_key.get(key)
            if existing is not None:
                if existing.input_fingerprint != input_fingerprint:
                    raise IdempotencyConflictError(
                        "The request ID was already used with different arguments."
                    )
                return CallStart(
                    call_id=existing.call_id,
                    created=False,
                    status=existing.status,
                    output=existing.output,
                    error_code=existing.error_code,
                    error_message=existing.error_message,
                )
            call = _Call(
                call_id=str(uuid.uuid4()),
                account_id=account_id,
                input_fingerprint=input_fingerprint,
            )
            self._calls_by_key[key] = call
            self._calls_by_id[call.call_id] = call
            return CallStart(call_id=call.call_id, created=True, status=CallStatus.STARTED)

    async def complete_call(
        self,
        *,
        call_id: str,
        output: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None:
        async with self._lock:
            self._complete_call(self._calls_by_id[call_id], output, sources)

    async def complete_preparation_call(
        self,
        *,
        call_id: str,
        draft: ActionDraft,
        output: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None:
        async with self._lock:
            call = self._calls_by_id[call_id]
            existing = self._actions.get(draft.action_id)
            if existing is not None and existing.draft != draft:
                raise IdempotencyConflictError("The action ID already belongs to another draft.")
            self._actions[draft.action_id] = _Action(
                account_id=call.account_id,
                draft=draft,
            )
            self._complete_call(call, output, sources)

    def _complete_call(
        self,
        call: _Call,
        output: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None:
        for source in sources:
            self._sources[(call.account_id, source.source_id)] = source
        call.status = CallStatus.COMPLETED
        call.output = output

    async def fail_call(
        self,
        *,
        call_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        async with self._lock:
            call = self._calls_by_id[call_id]
            call.status = CallStatus.FAILED
            call.error_code = error_code
            call.error_message = error_message

    async def get_source(self, *, account_id: str, source_id: str) -> CapturedSource | None:
        return self._sources.get((account_id, source_id))

    async def get_action(self, *, account_id: str, action_id: str) -> ActionDraft | None:
        async with self._lock:
            action = self._actions.get(action_id)
            if action is None or action.account_id != account_id:
                return None
            return self._expire_action(action)

    async def begin_action_attempt(
        self,
        *,
        account_id: str,
        action_id: str,
        expected_action_type: ActionType,
        expected_payload_hash: str,
        approval_preview: ActionApprovalPreview,
        idempotency_key: str,
    ) -> ActionAttemptStart:
        now = datetime.now(UTC)
        async with self._lock:
            existing = self._attempts_by_key.get(idempotency_key)
            if existing is not None:
                if existing.account_id != account_id or existing.action_id != action_id:
                    raise IdempotencyConflictError(
                        "The execution idempotency key belongs to a different action."
                    )
                action = self._required_action(account_id, action_id)
                if action.draft.action_type is not expected_action_type:
                    raise InvalidTargetError("The action type does not match this execute tool.")
                self._validate_confirmation(
                    action.draft,
                    expected_payload_hash=expected_payload_hash,
                    approval_preview=approval_preview,
                )
                if existing.status is AttemptStatus.EXECUTING:
                    raise IdempotencyConflictError("The confirmed action is already executing.")
                return ActionAttemptStart(
                    attempt_id=existing.attempt_id,
                    action=action.draft,
                    created=False,
                    status=existing.status,
                    started_at=existing.started_at,
                    result=existing.result,
                    sources=existing.sources,
                )

            action = self._required_action(account_id, action_id)
            draft = self._expire_action(action, now=now)
            if draft.status is ActionStatus.EXPIRED:
                raise AuthorizationDeniedError("The action draft has expired.")
            if draft.action_type is not expected_action_type:
                raise InvalidTargetError("The action type does not match this execute tool.")
            self._validate_confirmation(
                draft,
                expected_payload_hash=expected_payload_hash,
                approval_preview=approval_preview,
            )
            if draft.status is not ActionStatus.READY_FOR_CONFIRMATION:
                raise IdempotencyConflictError(
                    f"Action status {draft.status.value!r} cannot begin execution."
                )
            attempt = _Attempt(
                attempt_id=str(uuid.uuid4()),
                account_id=account_id,
                action_id=action_id,
                idempotency_key=idempotency_key,
                status=AttemptStatus.EXECUTING,
                started_at=now,
            )
            self._attempts_by_key[idempotency_key] = attempt
            self._attempts_by_id[attempt.attempt_id] = attempt
            action.draft = draft.model_copy(update={"status": ActionStatus.EXECUTING})
            return ActionAttemptStart(
                attempt_id=attempt.attempt_id,
                action=action.draft,
                created=True,
                status=attempt.status,
                started_at=attempt.started_at,
            )

    async def complete_action_attempt(
        self,
        *,
        account_id: str,
        context_id: str,
        attempt_id: str,
        outcome: ActionOutcome,
        result: dict[str, object],
        sources: tuple[CapturedSource, ...],
    ) -> None:
        del context_id
        async with self._lock:
            attempt = self._attempts_by_id.get(attempt_id)
            if attempt is None or attempt.account_id != account_id:
                raise InvalidTargetError("The action attempt does not exist for this account.")
            expected_status = AttemptStatus(outcome.value)
            if attempt.status is not AttemptStatus.EXECUTING:
                if attempt.status is expected_status and attempt.result == result:
                    return
                raise IdempotencyConflictError("The action attempt is already terminal.")
            action = self._required_action(account_id, attempt.action_id)
            attempt.status = expected_status
            attempt.result = result
            attempt.sources = sources
            for source in sources:
                self._sources[(account_id, source.source_id)] = source
            action.draft = action.draft.model_copy(update={"status": ActionStatus(outcome.value)})

    def _required_action(self, account_id: str, action_id: str) -> _Action:
        action = self._actions.get(action_id)
        if action is None or action.account_id != account_id:
            raise InvalidTargetError("The action draft does not exist for this account.")
        return action

    @staticmethod
    def _validate_confirmation(
        draft: ActionDraft,
        *,
        expected_payload_hash: str,
        approval_preview: ActionApprovalPreview,
    ) -> None:
        if expected_payload_hash != draft.payload_hash:
            raise AuthorizationDeniedError(
                "The execution payload hash does not match the immutable action draft."
            )
        if approval_preview != action_approval_preview(draft):
            raise AuthorizationDeniedError(
                "The approval preview does not match the immutable action draft."
            )

    @staticmethod
    def _expire_action(
        action: _Action,
        *,
        now: datetime | None = None,
    ) -> ActionDraft:
        checked_at = now or datetime.now(UTC)
        if (
            action.draft.expires_at <= checked_at
            and action.draft.status is ActionStatus.READY_FOR_CONFIRMATION
        ):
            action.draft = action.draft.model_copy(update={"status": ActionStatus.EXPIRED})
        return action.draft

    async def close(self) -> None:
        return
