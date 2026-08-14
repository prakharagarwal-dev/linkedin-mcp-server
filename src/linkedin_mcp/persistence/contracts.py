"""Process-local operation contracts for capability execution and evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from linkedin_mcp.domain.models import CapabilityName, CapturedSource


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


class Repository(Protocol):
    async def find_call(
        self,
        *,
        account_id: str,
        client_id: str = "direct-local-client",
        request_id: str,
        capability_name: CapabilityName,
    ) -> CallStart | None: ...

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
    ) -> CallStart: ...

    async def complete_call(
        self,
        *,
        call_id: str,
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

    async def close(self) -> None: ...
