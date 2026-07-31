"""Process-local immutable snapshot pagination for LinkedIn invitations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from linkedin_mcp.domain.models import (
    CapabilityName,
    InvitationListCoverage,
    InvitationListInput,
    InvitationSummary,
    PaginationMetadata,
)
from linkedin_mcp.errors import InvalidCursorError

Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class InvitationSnapshot:
    invitations: tuple[InvitationSummary, ...]
    coverage: InvitationListCoverage
    advertised_label: str
    source_url: str

    def __post_init__(self) -> None:
        if (
            len(self.invitations) != self.coverage.snapshot_count
            or self.coverage.returned_count != self.coverage.snapshot_count
        ):
            raise ValueError("Invitation snapshot items conflict with snapshot coverage.")
        if not self.advertised_label.strip():
            raise ValueError("Invitation snapshots require visible advertised-count evidence.")


@dataclass(slots=True)
class _SnapshotCursorState:
    account_id: str
    binding: str
    scan_id: str
    snapshot: InvitationSnapshot
    offset: int
    expires_at: datetime
    reserved_by: str | None = None


@dataclass(frozen=True, slots=True)
class InvitationSnapshotLease:
    lease_id: str
    token: str
    state: _SnapshotCursorState

    @property
    def snapshot(self) -> InvitationSnapshot:
        return self.state.snapshot


def _request_binding(request: InvitationListInput) -> str:
    payload = json.dumps(
        {
            "capability": CapabilityName.INVITATIONS_LIST.value,
            "direction": request.direction.value,
            "filter": request.resolved_filter.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


class InvitationSnapshotPaginator:
    """Serve one captured invitation inventory through single-use opaque cursors."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_active_cursors: int,
        max_snapshot_items: int,
        clock: Clock | None = None,
    ) -> None:
        if ttl_seconds < 1:
            raise ValueError("Invitation cursor TTL must be positive.")
        if max_active_cursors < 1:
            raise ValueError("Invitation cursor capacity must be positive.")
        if max_snapshot_items < 1:
            raise ValueError("Invitation snapshot capacity must be positive.")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_active_cursors = max_active_cursors
        self._max_snapshot_items = max_snapshot_items
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states: dict[str, _SnapshotCursorState] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        account_id: str,
        request: InvitationListInput,
        snapshot: InvitationSnapshot,
    ) -> tuple[tuple[InvitationSummary, ...], PaginationMetadata]:
        if request.cursor is not None:
            raise ValueError("A new invitation snapshot cannot start from a cursor.")
        if len(snapshot.invitations) > self._max_snapshot_items:
            raise ValueError("The invitation snapshot exceeds process-local capacity.")

        scan_id = str(uuid.uuid4())
        items = snapshot.invitations[: request.page_size]
        has_more = len(items) < len(snapshot.invitations)
        token: str | None = None
        expires_at: datetime | None = None
        async with self._lock:
            now = self._clock()
            self._prune_expired(now)
            if has_more:
                self._make_room()
                token = self._new_token()
                expires_at = now + self._ttl
                self._states[token] = _SnapshotCursorState(
                    account_id=account_id,
                    binding=_request_binding(request),
                    scan_id=scan_id,
                    snapshot=snapshot,
                    offset=len(items),
                    expires_at=expires_at,
                )
        return items, PaginationMetadata(
            scan_id=scan_id,
            page_size=request.page_size,
            returned_count=len(items),
            cumulative_count=len(items),
            has_more=has_more,
            next_cursor=token,
            cursor_expires_at=expires_at,
            consistency="captured_snapshot",
        )

    async def acquire(
        self,
        *,
        account_id: str,
        request: InvitationListInput,
    ) -> InvitationSnapshotLease:
        if request.cursor is None:
            raise ValueError("An invitation continuation requires a cursor.")
        lease_id = str(uuid.uuid4())
        async with self._lock:
            now = self._clock()
            self._prune_expired(now)
            state = self._states.get(request.cursor)
            if state is None:
                raise InvalidCursorError(
                    "The invitation cursor is invalid, expired, consumed, or belongs to another "
                    "server process."
                )
            if state.expires_at <= now:
                self._states.pop(request.cursor, None)
                raise InvalidCursorError("The invitation cursor has expired.")
            if state.account_id != account_id or state.binding != _request_binding(request):
                raise InvalidCursorError(
                    "The invitation cursor does not match this account, direction, or filter."
                )
            if state.reserved_by is not None:
                raise InvalidCursorError("The invitation cursor is already in use.")
            state.reserved_by = lease_id
            return InvitationSnapshotLease(
                lease_id=lease_id,
                token=request.cursor,
                state=state,
            )

    @staticmethod
    def page(
        lease: InvitationSnapshotLease,
        *,
        page_size: int,
    ) -> tuple[InvitationSummary, ...]:
        start = lease.state.offset
        return lease.state.snapshot.invitations[start : start + page_size]

    async def advance(
        self,
        lease: InvitationSnapshotLease,
        *,
        page_size: int,
        returned_count: int,
    ) -> PaginationMetadata:
        expected = self.page(lease, page_size=page_size)
        if returned_count != len(expected):
            raise ValueError("Invitation cursor advancement conflicts with the selected page.")
        async with self._lock:
            state = self._states.get(lease.token)
            if state is None or state is not lease.state or state.reserved_by != lease.lease_id:
                raise InvalidCursorError("The invitation cursor lease is no longer valid.")
            now = self._clock()
            if state.expires_at <= now:
                self._states.pop(lease.token, None)
                raise InvalidCursorError("The invitation cursor expired while it was in use.")

            self._states.pop(lease.token, None)
            offset = state.offset + returned_count
            has_more = offset < len(state.snapshot.invitations)
            next_cursor: str | None = None
            expires_at: datetime | None = None
            if has_more:
                next_cursor = self._new_token()
                expires_at = state.expires_at
                self._states[next_cursor] = _SnapshotCursorState(
                    account_id=state.account_id,
                    binding=state.binding,
                    scan_id=state.scan_id,
                    snapshot=state.snapshot,
                    offset=offset,
                    expires_at=state.expires_at,
                )
            return PaginationMetadata(
                scan_id=state.scan_id,
                page_size=page_size,
                returned_count=returned_count,
                cumulative_count=offset,
                has_more=has_more,
                next_cursor=next_cursor,
                cursor_expires_at=expires_at,
                consistency="captured_snapshot",
            )

    async def abort(self, lease: InvitationSnapshotLease) -> None:
        async with self._lock:
            state = self._states.get(lease.token)
            if state is not None and state is lease.state and state.reserved_by == lease.lease_id:
                state.reserved_by = None

    async def close(self) -> None:
        async with self._lock:
            self._states.clear()

    def _prune_expired(self, now: datetime) -> None:
        for token, state in tuple(self._states.items()):
            if state.expires_at <= now and state.reserved_by is None:
                self._states.pop(token, None)

    def _make_room(self) -> None:
        if len(self._states) < self._max_active_cursors:
            return
        candidates = [
            (state.expires_at, token)
            for token, state in self._states.items()
            if state.reserved_by is None
        ]
        if not candidates:
            raise InvalidCursorError("The local invitation cursor capacity is temporarily full.")
        _, token = min(candidates)
        self._states.pop(token, None)

    def _new_token(self) -> str:
        token = secrets.token_urlsafe(32)
        while token in self._states:
            token = secrets.token_urlsafe(32)
        return token
