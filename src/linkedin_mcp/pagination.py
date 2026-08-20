"""Bounded process-local cursor state for live LinkedIn collection scans."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from linkedin_mcp.errors import InvalidCursorError
from linkedin_mcp.tools._shared.models import CapabilityName, PaginatedInput, PaginationMetadata
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput

Clock = Callable[[], datetime]


@dataclass(slots=True)
class _CursorState:
    account_id: str
    capability_name: CapabilityName
    binding: str
    scan_id: str
    seen_keys: tuple[str, ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PaginationState:
    """Cursor state needed by one serialized collection task."""

    account_id: str
    capability_name: CapabilityName
    binding: str
    scan_id: str
    seen_keys: frozenset[str]
    prior_cursor: str | None

    @property
    def cumulative_count(self) -> int:
        return len(self.seen_keys)


@dataclass(frozen=True, slots=True)
class PageSlice[ItemT]:
    items: tuple[ItemT, ...]
    keys: tuple[str, ...]
    has_lookahead: bool


def request_binding(
    capability_name: CapabilityName,
    request: PaginatedInput,
) -> str:
    """Bind a cursor to every semantic argument except call and page state."""

    value = request.model_dump(
        mode="json",
        exclude={"context_id", "request_id", "cursor", "page_size"},
    )
    if isinstance(request, InvitationListInput):
        value["invitation_filter"] = request.resolved_filter.value
    payload = json.dumps(
        {
            "capability": capability_name.value,
            "input": value,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def select_page[ItemT](
    values: tuple[ItemT, ...],
    *,
    key: Callable[[ItemT], str],
    seen_keys: frozenset[str],
    page_size: int,
) -> PageSlice[ItemT]:
    """Select unseen values in visible order and retain one-item lookahead."""

    unseen: list[tuple[str, ItemT]] = []
    local_keys: set[str] = set()
    for value in values:
        item_key = key(value)
        if item_key in seen_keys or item_key in local_keys:
            continue
        local_keys.add(item_key)
        unseen.append((item_key, value))
        if len(unseen) > page_size:
            break
    selected = unseen[:page_size]
    return PageSlice(
        items=tuple(value for _, value in selected),
        keys=tuple(item_key for item_key, _ in selected),
        has_lookahead=len(unseen) > page_size,
    )


class PaginationManager:
    """Issue single-use cursors backed only by bounded in-process memory."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_active_cursors: int,
        max_seen_items_per_cursor: int,
        clock: Clock | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_active_cursors = max_active_cursors
        self._max_seen_items = max_seen_items_per_cursor
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states: dict[str, _CursorState] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        account_id: str,
        capability_name: CapabilityName,
        request: PaginatedInput,
    ) -> PaginationState:
        binding = request_binding(capability_name, request)
        async with self._lock:
            now = self._clock()
            self._prune_expired(now)
            if request.cursor is None:
                return PaginationState(
                    account_id=account_id,
                    capability_name=capability_name,
                    binding=binding,
                    scan_id=str(uuid.uuid4()),
                    seen_keys=frozenset(),
                    prior_cursor=None,
                )

            state = self._states.get(request.cursor)
            if state is None:
                raise InvalidCursorError(
                    "The pagination cursor is invalid, expired, consumed, or belongs to another "
                    "server process."
                )
            if state.expires_at <= now:
                self._states.pop(request.cursor, None)
                raise InvalidCursorError("The pagination cursor has expired.")
            if (
                state.account_id != account_id
                or state.capability_name is not capability_name
                or state.binding != binding
            ):
                raise InvalidCursorError(
                    "The pagination cursor does not match this account, capability, or filter set."
                )
            return PaginationState(
                account_id=account_id,
                capability_name=capability_name,
                binding=binding,
                scan_id=state.scan_id,
                seen_keys=frozenset(state.seen_keys),
                prior_cursor=request.cursor,
            )

    def traversal_limit(self, state: PaginationState, page_size: int) -> int:
        """Request a prefix containing prior identities plus one unseen lookahead."""

        return min(
            self._max_seen_items + 1,
            state.cumulative_count + page_size + 1,
        )

    def page_capacity(self, state: PaginationState, page_size: int) -> int:
        """Keep a returned page inside the configured per-scan identity bound."""

        return max(
            0,
            min(page_size, self._max_seen_items - state.cumulative_count),
        )

    async def finish(
        self,
        state: PaginationState,
        *,
        page_size: int,
        returned_keys: tuple[str, ...],
        provider_has_more: bool,
        force_truncated: bool = False,
    ) -> PaginationMetadata:
        if len(set(returned_keys)) != len(returned_keys):
            raise ValueError("A pagination page cannot contain duplicate stable identities.")
        if any(item_key in state.seen_keys for item_key in returned_keys):
            raise ValueError("A pagination page cannot repeat an earlier stable identity.")

        async with self._lock:
            if state.prior_cursor is not None:
                current = self._states.get(state.prior_cursor)
                if current is None or (
                    current.account_id != state.account_id
                    or current.capability_name is not state.capability_name
                    or current.binding != state.binding
                    or current.scan_id != state.scan_id
                    or frozenset(current.seen_keys) != state.seen_keys
                ):
                    raise InvalidCursorError("The pagination cursor is no longer valid.")
                self._states.pop(state.prior_cursor, None)

            combined = (*sorted(state.seen_keys), *returned_keys)
            capacity_reached = provider_has_more and len(combined) >= self._max_seen_items
            stalled = provider_has_more and not returned_keys
            truncated = force_truncated or capacity_reached or stalled
            has_more = provider_has_more and not truncated
            next_cursor: str | None = None
            expires_at: datetime | None = None
            if has_more:
                self._make_room()
                next_cursor = self._new_token()
                expires_at = self._clock() + self._ttl
                self._states[next_cursor] = _CursorState(
                    account_id=state.account_id,
                    capability_name=state.capability_name,
                    binding=state.binding,
                    scan_id=state.scan_id,
                    seen_keys=combined,
                    expires_at=expires_at,
                )
            return PaginationMetadata(
                scan_id=state.scan_id,
                page_size=page_size,
                returned_count=len(returned_keys),
                cumulative_count=len(combined),
                has_more=has_more,
                next_cursor=next_cursor,
                cursor_expires_at=expires_at,
                truncated=truncated,
            )

    async def close(self) -> None:
        async with self._lock:
            self._states.clear()

    def _prune_expired(self, now: datetime) -> None:
        for token, state in tuple(self._states.items()):
            if state.expires_at <= now:
                self._states.pop(token, None)

    def _make_room(self) -> None:
        if len(self._states) < self._max_active_cursors:
            return
        candidates = [(state.expires_at, token) for token, state in self._states.items()]
        _, oldest_token = min(candidates)
        self._states.pop(oldest_token, None)

    def _new_token(self) -> str:
        token = secrets.token_urlsafe(32)
        while token in self._states:
            token = secrets.token_urlsafe(32)
        return token
