from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from linkedin_mcp.application.pagination import PaginationManager, select_page
from linkedin_mcp.domain.models import (
    CapabilityName,
    ConnectionsListInput,
    InvitationFilter,
    InvitationListInput,
    JobSearchInput,
    PostCommentsListInput,
)
from linkedin_mcp.errors import InvalidCursorError


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 7, 28, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _manager(
    *,
    clock: MutableClock | None = None,
    max_active_cursors: int = 4,
    max_seen_items: int = 100,
) -> PaginationManager:
    return PaginationManager(
        ttl_seconds=60,
        max_active_cursors=max_active_cursors,
        max_seen_items_per_cursor=max_seen_items,
        clock=clock,
    )


def test_paginated_models_accept_legacy_limits_but_advertise_canonical_fields() -> None:
    jobs = JobSearchInput.model_validate(
        {
            "context_id": "pagination",
            "request_id": "legacy-jobs",
            "query": "python",
            "max_results": 7,
        }
    )
    comments = PostCommentsListInput.model_validate(
        {
            "context_id": "pagination",
            "request_id": "legacy-comments",
            "post_ref": "activity:7312345678901234567",
            "max_comments": 9,
        }
    )

    assert jobs.page_size == jobs.max_results == 7
    assert comments.page_size == comments.max_comments == 9
    assert {"page_size", "cursor"}.issubset(JobSearchInput.model_json_schema()["properties"])
    assert "max_results" not in JobSearchInput.model_json_schema()["properties"]
    assert "max_comments" not in PostCommentsListInput.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_cursor_continuation_is_single_use_and_preserves_scan_identity() -> None:
    manager = _manager()
    first_request = ConnectionsListInput(
        context_id="pagination",
        request_id="page-1",
        page_size=2,
    )
    first_lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=first_request,
    )
    page = select_page(
        ("alice", "alice", "bob", "carol"),
        key=lambda value: value,
        seen_keys=first_lease.seen_keys,
        page_size=first_request.page_size,
    )

    assert page.items == ("alice", "bob")
    assert page.keys == ("alice", "bob")
    assert page.has_lookahead is True
    assert manager.traversal_limit(first_lease, first_request.page_size) == 3

    first = await manager.advance(
        first_lease,
        page_size=first_request.page_size,
        returned_keys=page.keys,
        provider_has_more=True,
    )
    assert first.returned_count == 2
    assert first.cumulative_count == 2
    assert first.has_more is True
    assert first.next_cursor is not None

    continuation = ConnectionsListInput(
        context_id="pagination",
        request_id="page-2",
        page_size=1,
        cursor=first.next_cursor,
    )
    second_lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=continuation,
    )
    assert second_lease.scan_id == first.scan_id
    assert second_lease.seen_keys == frozenset({"alice", "bob"})
    assert manager.traversal_limit(second_lease, continuation.page_size) == 4

    with pytest.raises(InvalidCursorError, match="already in use"):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.CONNECTIONS_LIST,
            request=continuation.model_copy(update={"request_id": "parallel-attempt"}),
        )

    await manager.abort(second_lease)
    retry_lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=continuation.model_copy(update={"request_id": "page-2-retry"}),
    )
    terminal = await manager.advance(
        retry_lease,
        page_size=continuation.page_size,
        returned_keys=("carol",),
        provider_has_more=False,
    )

    assert terminal.scan_id == first.scan_id
    assert terminal.cumulative_count == 3
    assert terminal.has_more is False
    assert terminal.next_cursor is None
    with pytest.raises(InvalidCursorError, match="invalid, expired, consumed"):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.CONNECTIONS_LIST,
            request=continuation.model_copy(update={"request_id": "cursor-replay"}),
        )


@pytest.mark.asyncio
async def test_cursor_is_bound_to_account_capability_and_semantic_filters() -> None:
    manager = _manager()
    request = JobSearchInput(
        context_id="pagination",
        request_id="page-1",
        query="python",
        location="India",
        page_size=2,
    )
    lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.JOBS_SEARCH,
        request=request,
    )
    first = await manager.advance(
        lease,
        page_size=request.page_size,
        returned_keys=("job-1", "job-2"),
        provider_has_more=True,
    )
    assert first.next_cursor is not None
    continuation = request.model_copy(
        update={
            "request_id": "page-2",
            "cursor": first.next_cursor,
            "page_size": 3,
        }
    )

    with pytest.raises(InvalidCursorError, match="does not match"):
        await manager.acquire(
            account_id="other-account",
            capability_name=CapabilityName.JOBS_SEARCH,
            request=continuation,
        )
    with pytest.raises(InvalidCursorError, match="does not match"):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.PEOPLE_SEARCH,
            request=continuation,
        )
    with pytest.raises(InvalidCursorError, match="does not match"):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.JOBS_SEARCH,
            request=continuation.model_copy(update={"query": "rust"}),
        )

    valid = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.JOBS_SEARCH,
        request=continuation,
    )
    assert valid.seen_keys == frozenset({"job-1", "job-2"})
    await manager.abort(valid)


@pytest.mark.asyncio
async def test_invitation_cursor_binds_the_resolved_default_filter() -> None:
    manager = _manager()
    request = InvitationListInput(
        context_id="pagination",
        request_id="invitations-page-1",
        page_size=1,
    )
    lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.INVITATIONS_LIST,
        request=request,
    )
    first = await manager.advance(
        lease,
        page_size=1,
        returned_keys=("invitation-1",),
        provider_has_more=True,
    )
    assert first.next_cursor is not None

    continuation = request.model_copy(
        update={
            "request_id": "invitations-page-2",
            "cursor": first.next_cursor,
            "invitation_filter": InvitationFilter.ALL,
        }
    )
    continued = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.INVITATIONS_LIST,
        request=continuation,
    )

    assert continued.seen_keys == frozenset({"invitation-1"})
    await manager.abort(continued)


@pytest.mark.asyncio
async def test_cursor_expires_and_does_not_survive_process_state_loss() -> None:
    clock = MutableClock()
    manager = _manager(clock=clock)
    request = ConnectionsListInput(
        context_id="pagination",
        request_id="page-1",
        page_size=1,
    )
    lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=request,
    )
    first = await manager.advance(
        lease,
        page_size=1,
        returned_keys=("alice",),
        provider_has_more=True,
    )
    assert first.next_cursor is not None
    continuation = request.model_copy(update={"request_id": "page-2", "cursor": first.next_cursor})

    clock.advance(61)
    with pytest.raises(InvalidCursorError):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.CONNECTIONS_LIST,
            request=continuation,
        )

    fresh_process = _manager()
    with pytest.raises(InvalidCursorError, match="another server process"):
        await fresh_process.acquire(
            account_id="personal",
            capability_name=CapabilityName.CONNECTIONS_LIST,
            request=continuation,
        )


@pytest.mark.asyncio
async def test_active_cursor_capacity_evicts_the_oldest_idle_cursor() -> None:
    clock = MutableClock()
    manager = _manager(clock=clock, max_active_cursors=1)

    first_lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=ConnectionsListInput(
            context_id="pagination",
            request_id="scan-1",
            page_size=1,
        ),
    )
    first = await manager.advance(
        first_lease,
        page_size=1,
        returned_keys=("alice",),
        provider_has_more=True,
    )
    assert first.next_cursor is not None
    clock.advance(1)

    second_lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=ConnectionsListInput(
            context_id="pagination",
            request_id="scan-2",
            page_size=1,
        ),
    )
    second = await manager.advance(
        second_lease,
        page_size=1,
        returned_keys=("bob",),
        provider_has_more=True,
    )
    assert second.next_cursor is not None

    with pytest.raises(InvalidCursorError):
        await manager.acquire(
            account_id="personal",
            capability_name=CapabilityName.CONNECTIONS_LIST,
            request=ConnectionsListInput(
                context_id="pagination",
                request_id="scan-1-page-2",
                page_size=1,
                cursor=first.next_cursor,
            ),
        )
    retained = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=ConnectionsListInput(
            context_id="pagination",
            request_id="scan-2-page-2",
            page_size=1,
            cursor=second.next_cursor,
        ),
    )
    await manager.abort(retained)


@pytest.mark.asyncio
async def test_seen_identity_bound_returns_an_honest_terminal_truncation() -> None:
    manager = _manager(max_seen_items=3)
    request = ConnectionsListInput(
        context_id="pagination",
        request_id="bounded",
        page_size=10,
    )
    lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=request,
    )
    assert manager.page_capacity(lease, request.page_size) == 3
    page = select_page(
        ("alice", "bob", "carol", "dave"),
        key=lambda value: value,
        seen_keys=lease.seen_keys,
        page_size=manager.page_capacity(lease, request.page_size),
    )
    result = await manager.advance(
        lease,
        page_size=request.page_size,
        returned_keys=page.keys,
        provider_has_more=page.has_lookahead,
    )

    assert result.returned_count == 3
    assert result.cumulative_count == 3
    assert result.truncated is True
    assert result.has_more is False
    assert result.next_cursor is None

    terminal_manager = _manager(max_seen_items=3)
    terminal_lease = await terminal_manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=request.model_copy(update={"request_id": "exact-terminal"}),
    )
    terminal = await terminal_manager.advance(
        terminal_lease,
        page_size=request.page_size,
        returned_keys=("alice", "bob", "carol"),
        provider_has_more=False,
    )
    assert terminal.truncated is False


@pytest.mark.asyncio
async def test_cursor_lease_rejects_duplicate_or_previously_seen_identities() -> None:
    manager = _manager()
    request = ConnectionsListInput(
        context_id="pagination",
        request_id="duplicates",
        page_size=2,
    )
    lease = await manager.acquire(
        account_id="personal",
        capability_name=CapabilityName.CONNECTIONS_LIST,
        request=request,
    )
    with pytest.raises(ValueError, match="duplicate"):
        await manager.advance(
            lease,
            page_size=2,
            returned_keys=("alice", "alice"),
            provider_has_more=True,
        )
    await manager.abort(lease)
