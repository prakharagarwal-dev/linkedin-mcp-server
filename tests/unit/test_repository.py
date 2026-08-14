from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl

from linkedin_mcp.domain.evidence import canonical_input_fingerprint
from linkedin_mcp.domain.models import CapabilityName, CapturedSource, SourceType
from linkedin_mcp.errors import IdempotencyConflictError
from linkedin_mcp.persistence.contracts import CallStatus
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


@pytest.mark.asyncio
async def test_completed_read_call_and_evidence_are_replayed() -> None:
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
async def test_read_request_identity_is_client_local_and_input_locked() -> None:
    repository = MemoryRepository()
    first = await repository.begin_call(
        account_id="personal",
        client_id="client-a",
        context_id="context-a",
        request_id="shared",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )
    second = await repository.begin_call(
        account_id="personal",
        client_id="client-b",
        context_id="context-b",
        request_id="shared",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="b" * 64,
        input_value={"query": "rust"},
    )
    assert first.call_id != second.call_id

    with pytest.raises(IdempotencyConflictError):
        await repository.begin_call(
            account_id="personal",
            client_id="client-a",
            context_id="context-a",
            request_id="shared",
            capability_name=CapabilityName.JOBS_SEARCH,
            input_fingerprint="b" * 64,
            input_value={"query": "rust"},
        )


@pytest.mark.asyncio
async def test_failed_read_call_retains_only_safe_error() -> None:
    repository = MemoryRepository()
    call = await repository.begin_call(
        account_id="personal",
        context_id="context",
        request_id="failed",
        capability_name=CapabilityName.JOBS_GET,
        input_fingerprint="a" * 64,
        input_value={"job_id": "4100000001"},
    )
    await repository.fail_call(
        call_id=call.call_id,
        error_code="browser_unavailable",
        error_message="The browser stopped.",
    )
    replay = await repository.begin_call(
        account_id="personal",
        context_id="context",
        request_id="failed",
        capability_name=CapabilityName.JOBS_GET,
        input_fingerprint="a" * 64,
        input_value={"job_id": "4100000001"},
    )
    assert replay.status is CallStatus.FAILED
    assert replay.error_code == "browser_unavailable"
    assert replay.error_message == "The browser stopped."


@pytest.mark.asyncio
async def test_repository_restart_has_no_prior_process_state() -> None:
    first = MemoryRepository()
    source = _source()
    call = await first.begin_call(
        account_id="personal",
        context_id="context",
        request_id="read",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )
    await first.complete_call(call_id=call.call_id, output={}, sources=(source,))

    restarted = MemoryRepository()
    repeated = await restarted.begin_call(
        account_id="personal",
        context_id="context",
        request_id="read",
        capability_name=CapabilityName.JOBS_SEARCH,
        input_fingerprint="a" * 64,
        input_value={"query": "python"},
    )
    assert repeated.created is True
    assert await restarted.get_source(account_id="personal", source_id=source.source_id) is None
