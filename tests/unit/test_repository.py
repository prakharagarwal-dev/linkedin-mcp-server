from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import pytest
from pydantic import HttpUrl

from linkedin_mcp.domain.evidence import canonical_input_fingerprint
from linkedin_mcp.domain.models import (
    ActionApprovalPreview,
    ActionDraft,
    ActionExecutionResult,
    ActionOutcome,
    ActionStatus,
    ActionTarget,
    ActionType,
    CapabilityName,
    CapturedSource,
    InvitationSendPayload,
    SourceType,
    action_approval_preview,
)
from linkedin_mcp.errors import (
    AuthorizationDeniedError,
    IdempotencyConflictError,
    InvalidTargetError,
)
from linkedin_mcp.persistence.contracts import AttemptStatus, CallStatus
from linkedin_mcp.persistence.memory import MemoryRepository


def _source() -> CapturedSource:
    return CapturedSource(
        source_id="linkedin_job_search:1234567890abcdef",
        source_type=SourceType.JOB_SEARCH,
        source_url=HttpUrl("https://www.linkedin.com/jobs/search/?keywords=python"),
        captured_at=datetime.now(UTC),
        captured_text="Senior Python Engineer",
        content={"jobs": []},
    )


def _draft(*, expires_at: datetime | None = None) -> ActionDraft:
    now = datetime.now(UTC)
    return ActionDraft(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.INVITATION_SEND,
        target=ActionTarget(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            display_name="Jane Doe",
        ),
        payload=InvitationSendPayload(note="Hello Jane"),
        payload_hash="a" * 64,
        status=ActionStatus.READY_FOR_CONFIRMATION,
        created_at=now,
        expires_at=expires_at or now + timedelta(hours=1),
    )


async def _store_draft(
    repository: MemoryRepository,
    draft: ActionDraft,
    *,
    request_id: str,
) -> None:
    call = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id=request_id,
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint=draft.payload_hash,
        input_value={"profile_slug": draft.target.profile_slug},
    )
    await repository.complete_preparation_call(
        call_id=call.call_id,
        draft=draft,
        output={},
        sources=(),
    )


class _ConfirmationKwargs(TypedDict):
    expected_payload_hash: str
    approval_preview: ActionApprovalPreview


def _confirmation(draft: ActionDraft) -> _ConfirmationKwargs:
    return {
        "expected_payload_hash": draft.payload_hash,
        "approval_preview": action_approval_preview(draft),
    }


@pytest.mark.asyncio
async def test_completed_call_is_replayed_without_a_second_execution() -> None:
    repository = MemoryRepository()
    input_value: dict[str, object] = {"query": "python"}
    fingerprint = canonical_input_fingerprint(input_value)
    first = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="request-1",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint=fingerprint,
        input_value=input_value,
    )
    source = _source()
    await repository.complete_call(
        call_id=first.call_id,
        output={"status": "completed"},
        sources=(source,),
    )

    replay = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="request-1",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint=fingerprint,
        input_value=input_value,
    )

    assert replay.created is False
    assert replay.status is CallStatus.COMPLETED
    assert replay.output == {"status": "completed"}
    assert await repository.get_source(account_id="personal", source_id=source.source_id) == source


@pytest.mark.asyncio
async def test_new_repository_starts_without_prior_operation_state() -> None:
    first = MemoryRepository()
    source = _source()
    draft = _draft()
    call = await first.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="prepare-1",
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint=draft.payload_hash,
        input_value={"profile_slug": draft.target.profile_slug},
    )
    await first.complete_preparation_call(
        call_id=call.call_id,
        draft=draft,
        output={"prepared": True},
        sources=(source,),
    )

    restarted = MemoryRepository()
    repeated = await restarted.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="prepare-1",
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint=draft.payload_hash,
        input_value={"profile_slug": draft.target.profile_slug},
    )

    assert repeated.created is True
    assert await restarted.get_source(account_id="personal", source_id=source.source_id) is None
    assert await restarted.get_action(account_id="personal", action_id=draft.action_id) is None


@pytest.mark.asyncio
async def test_request_id_reuse_with_different_input_is_rejected() -> None:
    repository = MemoryRepository()
    await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="request-1",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )

    with pytest.raises(IdempotencyConflictError):
        await repository.begin_call(
            account_id="personal",
            context_id="context-1",
            request_id="request-1",
            capability_name=CapabilityName.JOBS_SEARCH,
            input_fingerprint="b" * 64,
            input_value={"query": "rust"},
        )


@pytest.mark.asyncio
async def test_failed_call_retains_safe_error_for_idempotent_replay() -> None:
    repository = MemoryRepository()
    call = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="request-1",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )
    await repository.fail_call(
        call_id=call.call_id,
        error_code="browser_unavailable",
        error_message="The browser stopped.",
    )

    replay = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="request-1",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )

    assert replay.status is CallStatus.FAILED
    assert replay.error_code == "browser_unavailable"
    assert replay.error_message == "The browser stopped."


@pytest.mark.asyncio
async def test_action_draft_requires_exact_confirmation_and_replays_verified_attempt() -> None:
    repository = MemoryRepository()
    call = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="prepare-1",
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint="a" * 64,
        input_value={"profile_slug": "jane-doe"},
    )
    draft = _draft()
    source = _source()
    await repository.complete_preparation_call(
        call_id=call.call_id,
        draft=draft,
        output={"draft": draft.model_dump(mode="json")},
        sources=(source,),
    )

    with pytest.raises(AuthorizationDeniedError, match="hash"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=draft.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            expected_payload_hash="b" * 64,
            approval_preview=action_approval_preview(draft),
            idempotency_key="wrong-hash",
        )
    altered_preview = action_approval_preview(draft).model_copy(
        update={"summary": "Send a different action."}
    )
    with pytest.raises(AuthorizationDeniedError, match="preview"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=draft.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            expected_payload_hash=draft.payload_hash,
            approval_preview=altered_preview,
            idempotency_key="wrong-preview",
        )

    attempt = await repository.begin_action_attempt(
        account_id="personal",
        action_id=draft.action_id,
        expected_action_type=ActionType.INVITATION_SEND,
        **_confirmation(draft),
        idempotency_key="invite-attempt-1",
    )
    assert attempt.created is True
    assert attempt.status is AttemptStatus.EXECUTING
    with pytest.raises(IdempotencyConflictError, match="already executing"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=draft.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            **_confirmation(draft),
            idempotency_key="invite-attempt-1",
        )

    completed_at = datetime.now(UTC)
    result = ActionExecutionResult(
        action_id=draft.action_id,
        action_type=ActionType.INVITATION_SEND,
        attempt_id=attempt.attempt_id,
        idempotency_key="invite-attempt-1",
        outcome=ActionOutcome.VERIFIED,
        performed=True,
        final_state="pending_sent",
        detail="Invitation visibly pending.",
        started_at=attempt.started_at,
        completed_at=completed_at,
    )
    await repository.complete_action_attempt(
        account_id="personal",
        context_id="context-1",
        attempt_id=attempt.attempt_id,
        outcome=ActionOutcome.VERIFIED,
        result=result.model_dump(mode="json"),
        sources=(source,),
    )

    replay = await repository.begin_action_attempt(
        account_id="personal",
        action_id=draft.action_id,
        expected_action_type=ActionType.INVITATION_SEND,
        **_confirmation(draft),
        idempotency_key="invite-attempt-1",
    )
    assert replay.created is False
    assert replay.status is AttemptStatus.VERIFIED
    assert replay.result == result.model_dump(mode="json")
    assert replay.sources == (source,)
    stored = await repository.get_action(
        account_id="personal",
        action_id=draft.action_id,
    )
    assert stored is not None
    assert stored.status is ActionStatus.VERIFIED


@pytest.mark.asyncio
async def test_expired_actions_fail_closed() -> None:
    repository = MemoryRepository()
    expired_call = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="expired-prepare",
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint="a" * 64,
        input_value={"profile_slug": "jane-doe"},
    )
    expired = _draft(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    await repository.complete_preparation_call(
        call_id=expired_call.call_id,
        draft=expired,
        output={},
        sources=(),
    )
    stored_expired = await repository.get_action(
        account_id="personal",
        action_id=expired.action_id,
    )
    assert stored_expired is not None
    assert stored_expired.status is ActionStatus.EXPIRED
    with pytest.raises(AuthorizationDeniedError, match="expired"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=expired.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            **_confirmation(expired),
            idempotency_key="expired-action",
        )


@pytest.mark.asyncio
async def test_memory_action_ledger_rejects_conflicts_and_invalid_transitions() -> None:
    repository = MemoryRepository()
    draft = _draft()
    await _store_draft(repository, draft, request_id="strict-draft-1")

    assert (
        await repository.get_action(
            account_id="another-account",
            action_id=draft.action_id,
        )
        is None
    )
    with pytest.raises(InvalidTargetError, match="does not exist"):
        await repository.begin_action_attempt(
            account_id="another-account",
            action_id=draft.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            **_confirmation(draft),
            idempotency_key="wrong-account",
        )

    duplicate_call = await repository.begin_call(
        account_id="personal",
        context_id="context-1",
        request_id="duplicate-action-id",
        capability_name=CapabilityName.INVITATION_SEND_PREPARE,
        input_fingerprint="b" * 64,
        input_value={"profile_slug": "jane-doe"},
    )
    conflicting_draft = draft.model_copy(
        update={
            "payload": InvitationSendPayload(note="Different note"),
            "payload_hash": "b" * 64,
        }
    )
    with pytest.raises(IdempotencyConflictError, match="action ID"):
        await repository.complete_preparation_call(
            call_id=duplicate_call.call_id,
            draft=conflicting_draft,
            output={},
            sources=(),
        )

    mismatched = _draft()
    await _store_draft(repository, mismatched, request_id="mismatched-draft")
    with pytest.raises(InvalidTargetError, match="action type"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=mismatched.action_id,
            expected_action_type=ActionType.MESSAGE_SEND,
            **_confirmation(mismatched),
            idempotency_key="wrong-action-type",
        )
    with pytest.raises(AuthorizationDeniedError, match="preview"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=mismatched.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            expected_payload_hash=mismatched.payload_hash,
            approval_preview=action_approval_preview(draft),
            idempotency_key="mismatched-preview",
        )

    attempt = await repository.begin_action_attempt(
        account_id="personal",
        action_id=draft.action_id,
        expected_action_type=ActionType.INVITATION_SEND,
        **_confirmation(draft),
        idempotency_key="strict-attempt",
    )
    with pytest.raises(InvalidTargetError, match="attempt does not exist"):
        await repository.complete_action_attempt(
            account_id="personal",
            context_id="context-1",
            attempt_id=str(uuid.uuid4()),
            outcome=ActionOutcome.VERIFIED,
            result={},
            sources=(),
        )

    result: dict[str, object] = {"outcome": "verified"}
    await repository.complete_action_attempt(
        account_id="personal",
        context_id="context-1",
        attempt_id=attempt.attempt_id,
        outcome=ActionOutcome.VERIFIED,
        result=result,
        sources=(),
    )
    await repository.complete_action_attempt(
        account_id="personal",
        context_id="context-1",
        attempt_id=attempt.attempt_id,
        outcome=ActionOutcome.VERIFIED,
        result=result,
        sources=(),
    )
    with pytest.raises(IdempotencyConflictError, match="already terminal"):
        await repository.complete_action_attempt(
            account_id="personal",
            context_id="context-1",
            attempt_id=attempt.attempt_id,
            outcome=ActionOutcome.VERIFIED,
            result={"outcome": "different"},
            sources=(),
        )

    another = _draft()
    await _store_draft(repository, another, request_id="strict-draft-2")
    with pytest.raises(IdempotencyConflictError, match="different action"):
        await repository.begin_action_attempt(
            account_id="personal",
            action_id=another.action_id,
            expected_action_type=ActionType.INVITATION_SEND,
            **_confirmation(another),
            idempotency_key="strict-attempt",
        )
