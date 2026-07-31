from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import HttpUrl

from linkedin_mcp.application.invitation_snapshots import (
    InvitationSnapshot,
    InvitationSnapshotPaginator,
)
from linkedin_mcp.domain.models import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    InvitationAvailableAction,
    InvitationDirection,
    InvitationEntity,
    InvitationEntityType,
    InvitationEvidence,
    InvitationFilter,
    InvitationListCoverage,
    InvitationListInput,
    InvitationSummary,
    InvitationType,
)
from linkedin_mcp.errors import InvalidCursorError

SOURCE_URL = "https://www.linkedin.com/mynetwork/invitation-manager/received/"


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _request(
    request_id: str,
    *,
    page_size: int = 25,
    cursor: str | None = None,
    direction: InvitationDirection = InvitationDirection.RECEIVED,
    invitation_filter: InvitationFilter | None = None,
) -> InvitationListInput:
    return InvitationListInput(
        context_id="snapshot-tests",
        request_id=request_id,
        page_size=page_size,
        cursor=cursor,
        direction=direction,
        invitation_filter=invitation_filter,
    )


def _snapshot(size: int, *, captured_at: datetime | None = None) -> InvitationSnapshot:
    captured_at = captured_at or datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
    invitations = tuple(_invitation(index, captured_at=captured_at) for index in range(size))
    counts = {InvitationType.CONNECTION_REQUEST: size} if size else {}
    entity_counts = {InvitationEntityType.PERSON: size} if size else {}
    return InvitationSnapshot(
        invitations=invitations,
        coverage=InvitationListCoverage(
            direction=InvitationDirection.RECEIVED,
            invitation_filter=InvitationFilter.ALL,
            advertised_count=None,
            unique_count=size,
            view_counts={
                invitation_filter: (size if invitation_filter is InvitationFilter.FOCUSED else 0)
                for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
            },
            view_source_urls={
                invitation_filter: HttpUrl(SOURCE_URL)
                for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
            },
            view_membership_count=size,
            overlap_count=0,
            snapshot_count=size,
            returned_count=size,
            scroll_rounds=0,
            collection_attempts=1,
            neighboring_recommendation_count=0,
            invitation_type_counts=counts,
            entity_type_counts=entity_counts,
            completion_reason="visible_view_union_reconciled",
            captured_at=captured_at,
        ),
        advertised_label=f"Focused ({size})\nOther (0)",
        source_url=SOURCE_URL,
    )


def _invitation(index: int, *, captured_at: datetime) -> InvitationSummary:
    name = f"Member {index}"
    slug = f"member-{index}"
    return InvitationSummary(
        invitation_ref=f"invitation:{index:024x}",
        direction=InvitationDirection.RECEIVED,
        invitation_type=InvitationType.CONNECTION_REQUEST,
        primary_entity=InvitationEntity(
            entity_ref=f"entity:{index:024x}",
            entity_type=InvitationEntityType.PERSON,
            entity_url=HttpUrl(f"https://www.linkedin.com/in/{slug}/"),
            display_name=name,
            slug=slug,
        ),
        available_actions=(InvitationAvailableAction.ACCEPT,),
        visible_text=f"{name}\nAccept",
        evidence=(
            InvitationEvidence(
                field="primary_entity.display_name",
                quote=name,
                source_url=HttpUrl(SOURCE_URL),
                captured_at=captured_at,
            ),
        ),
    )


def _paginator(
    *,
    clock: MutableClock | None = None,
    max_active_cursors: int = 64,
) -> InvitationSnapshotPaginator:
    return InvitationSnapshotPaginator(
        ttl_seconds=900,
        max_active_cursors=max_active_cursors,
        max_snapshot_items=5_000,
        clock=clock,
    )


@pytest.mark.parametrize("size", [0, 1, 25, 26, 100, 101, 180])
@pytest.mark.asyncio
async def test_every_page_is_a_disjoint_slice_of_one_immutable_snapshot(size: int) -> None:
    paginator = _paginator()
    snapshot = _snapshot(size)
    request = _request("page-0")
    items, metadata = await paginator.start(
        account_id="personal",
        request=request,
        snapshot=snapshot,
    )
    pages = [items]
    cursors: list[str] = []
    page_index = 1

    while metadata.next_cursor is not None:
        cursor = metadata.next_cursor
        cursors.append(cursor)
        continuation = _request(f"page-{page_index}", cursor=cursor)
        lease = await paginator.acquire(account_id="personal", request=continuation)
        items = paginator.page(lease, page_size=continuation.page_size)
        metadata = await paginator.advance(
            lease,
            page_size=continuation.page_size,
            returned_count=len(items),
        )
        pages.append(items)
        page_index += 1

    flattened = tuple(item for page in pages for item in page)
    references = [item.invitation_ref for item in flattened]
    assert flattened == snapshot.invitations
    assert len(references) == len(set(references)) == size
    assert metadata.cumulative_count == size
    assert metadata.has_more is False
    assert metadata.next_cursor is None
    assert metadata.consistency == "captured_snapshot"
    assert all("member" not in cursor.casefold() for cursor in cursors)


@pytest.mark.asyncio
async def test_continuation_may_change_page_size_without_rescanning() -> None:
    paginator = _paginator()
    first, metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=2),
        snapshot=_snapshot(7),
    )
    assert len(first) == 2
    assert metadata.next_cursor is not None

    continuation = _request(
        "second",
        page_size=3,
        cursor=metadata.next_cursor,
    )
    lease = await paginator.acquire(account_id="personal", request=continuation)
    second = paginator.page(lease, page_size=continuation.page_size)
    metadata = await paginator.advance(
        lease,
        page_size=continuation.page_size,
        returned_count=len(second),
    )

    assert [item.primary_entity.slug for item in second] == [
        "member-2",
        "member-3",
        "member-4",
    ]
    assert metadata.cumulative_count == 5
    assert metadata.has_more is True


@pytest.mark.asyncio
async def test_cursor_is_account_direction_and_filter_bound() -> None:
    paginator = _paginator()
    _, metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    assert metadata.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="does not match"):
        await paginator.acquire(
            account_id="other",
            request=_request("wrong-account", page_size=1, cursor=metadata.next_cursor),
        )
    with pytest.raises(InvalidCursorError, match="does not match"):
        await paginator.acquire(
            account_id="personal",
            request=_request(
                "wrong-filter",
                page_size=1,
                cursor=metadata.next_cursor,
                invitation_filter=InvitationFilter.VERIFIED,
            ),
        )

    valid = await paginator.acquire(
        account_id="personal",
        request=_request("valid", page_size=1, cursor=metadata.next_cursor),
    )
    await paginator.abort(valid)


@pytest.mark.asyncio
async def test_cursor_is_reserved_then_consumed_exactly_once() -> None:
    paginator = _paginator()
    _, metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    assert metadata.next_cursor is not None
    continuation = _request("second", page_size=1, cursor=metadata.next_cursor)
    lease = await paginator.acquire(account_id="personal", request=continuation)

    with pytest.raises(InvalidCursorError, match="already in use"):
        await paginator.acquire(account_id="personal", request=continuation)

    await paginator.abort(lease)
    lease = await paginator.acquire(account_id="personal", request=continuation)
    page = paginator.page(lease, page_size=1)
    await paginator.advance(lease, page_size=1, returned_count=len(page))

    with pytest.raises(InvalidCursorError, match="invalid, expired, consumed"):
        await paginator.acquire(account_id="personal", request=continuation)


@pytest.mark.asyncio
async def test_snapshot_expiry_is_absolute_across_cursor_pages() -> None:
    clock = MutableClock(datetime(2026, 7, 29, 9, 0, tzinfo=UTC))
    paginator = _paginator(clock=clock)
    _, first_metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    assert first_metadata.next_cursor is not None
    assert first_metadata.cursor_expires_at is not None
    original_expiry = first_metadata.cursor_expires_at

    clock.value += timedelta(minutes=14)
    continuation = _request("second", page_size=1, cursor=first_metadata.next_cursor)
    lease = await paginator.acquire(account_id="personal", request=continuation)
    page = paginator.page(lease, page_size=1)
    second_metadata = await paginator.advance(
        lease,
        page_size=1,
        returned_count=len(page),
    )
    assert second_metadata.cursor_expires_at == original_expiry
    assert second_metadata.next_cursor is not None

    clock.value += timedelta(minutes=2)
    with pytest.raises(InvalidCursorError, match="invalid, expired, consumed"):
        await paginator.acquire(
            account_id="personal",
            request=_request("third", page_size=1, cursor=second_metadata.next_cursor),
        )


@pytest.mark.asyncio
async def test_cursor_cannot_advance_after_absolute_expiry() -> None:
    clock = MutableClock(datetime(2026, 7, 29, 9, 0, tzinfo=UTC))
    paginator = _paginator(clock=clock)
    _, metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    assert metadata.next_cursor is not None
    continuation = _request("second", page_size=1, cursor=metadata.next_cursor)
    lease = await paginator.acquire(account_id="personal", request=continuation)
    page = paginator.page(lease, page_size=1)

    clock.value += timedelta(minutes=16)
    with pytest.raises(InvalidCursorError, match="expired while it was in use"):
        await paginator.advance(
            lease,
            page_size=1,
            returned_count=len(page),
        )

    with pytest.raises(InvalidCursorError, match="invalid, expired, consumed"):
        await paginator.acquire(account_id="personal", request=continuation)


@pytest.mark.asyncio
async def test_capacity_evicts_only_an_unreserved_old_snapshot() -> None:
    paginator = _paginator(max_active_cursors=1)
    _, first = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    _, second = await paginator.start(
        account_id="personal",
        request=_request("second", page_size=1),
        snapshot=_snapshot(4),
    )
    assert first.next_cursor is not None
    assert second.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="invalid, expired, consumed"):
        await paginator.acquire(
            account_id="personal",
            request=_request("old", page_size=1, cursor=first.next_cursor),
        )
    lease = await paginator.acquire(
        account_id="personal",
        request=_request("new", page_size=1, cursor=second.next_cursor),
    )
    await paginator.abort(lease)


@pytest.mark.asyncio
async def test_process_close_invalidates_every_snapshot_cursor() -> None:
    paginator = _paginator()
    _, metadata = await paginator.start(
        account_id="personal",
        request=_request("first", page_size=1),
        snapshot=_snapshot(3),
    )
    assert metadata.next_cursor is not None

    await paginator.close()

    with pytest.raises(InvalidCursorError, match="another server process"):
        await paginator.acquire(
            account_id="personal",
            request=_request("second", page_size=1, cursor=metadata.next_cursor),
        )
