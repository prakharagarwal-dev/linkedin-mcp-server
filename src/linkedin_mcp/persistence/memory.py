"""Process-local read-call replay and captured evidence."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from linkedin_mcp.domain.models import CapabilityName, CapturedSource
from linkedin_mcp.errors import IdempotencyConflictError
from linkedin_mcp.persistence.contracts import (
    CallStart,
    CallStatus,
    Repository,
)


@dataclass(slots=True)
class _Call:
    call_id: str
    account_id: str
    client_id: str
    input_fingerprint: str
    status: CallStatus = CallStatus.STARTED
    output: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None


class MemoryRepository(Repository):
    """Bound all operation state to one MCP process lifetime."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._calls_by_key: dict[tuple[str, str, CapabilityName, str], _Call] = {}
        self._calls_by_id: dict[str, _Call] = {}
        self._sources: dict[tuple[str, str], CapturedSource] = {}

    async def find_call(
        self,
        *,
        account_id: str,
        client_id: str = "direct-local-client",
        request_id: str,
        capability_name: CapabilityName,
    ) -> CallStart | None:
        async with self._lock:
            existing = self._calls_by_key.get((account_id, client_id, capability_name, request_id))
            if existing is None:
                return None
            return CallStart(
                call_id=existing.call_id,
                created=False,
                status=existing.status,
                output=existing.output,
                error_code=existing.error_code,
                error_message=existing.error_message,
            )

    async def begin_call(
        self,
        *,
        account_id: str,
        client_id: str = "direct-local-client",
        context_id: str,
        request_id: str,
        capability_name: CapabilityName,
        input_fingerprint: str,
        input_value: dict[str, object],
    ) -> CallStart:
        del context_id, input_value
        key = (account_id, client_id, capability_name, request_id)
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
                client_id=client_id,
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

    async def close(self) -> None:
        return
