from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import ValidationError

import linkedin_mcp.tools.invitations._shared.pages as invitation_pages
from linkedin_mcp.errors import BrowserUnavailableError, ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools.invitations._shared.pages import InvitationListPage
from linkedin_mcp.tools.invitations.list.models import (
    InvitationAvailableAction,
    InvitationDirection,
    InvitationEntityType,
    InvitationFilter,
    InvitationListCoverage,
    InvitationListInput,
    InvitationSummary,
    InvitationType,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin" / "invitations" / "latest"
_COUNT_LABELS = {
    InvitationFilter.FOCUSED: "Focused (4)",
    InvitationFilter.OTHER: "Other (3)",
}


@pytest.fixture(autouse=True)
def _fast_invitation_polling(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(invitation_pages, "_SETTLE_ATTEMPTS", 2)
    monkeypatch.setattr(invitation_pages, "_SETTLE_DELAY_MS", 10)
    monkeypatch.setattr(invitation_pages, "_INVENTORY_ATTEMPTS", 2)
    monkeypatch.setattr(invitation_pages, "_INVENTORY_DELAY_MS", 10)


@pytest.fixture
async def invitation_page() -> AsyncGenerator[Page]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


class InvitationFixtureBrowser:
    def __init__(self, page: Page, fixtures_by_path: dict[str, str]) -> None:
        self._page = page
        self._fixtures_by_path = fixtures_by_path
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        path = urlsplit(url).path
        matching = sorted(
            (candidate for candidate in self._fixtures_by_path if path.startswith(candidate)),
            key=len,
            reverse=True,
        )
        if not matching:
            raise ValueError(f"No invitation fixture is registered for {path}.")
        html = self._fixtures_by_path[matching[0]]

        async def fulfill(route: Route) -> None:
            await route.fulfill(status=200, content_type="text/html", body=html)

        await page.route(url, fulfill, times=1)
        await page.goto(url, wait_until="domcontentloaded")
        self.navigations.append(path)

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        await control.click()
        await page.wait_for_timeout(1)


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _request(
    *,
    direction: InvitationDirection = InvitationDirection.RECEIVED,
    invitation_filter: InvitationFilter | None = None,
) -> InvitationListInput:
    selected_filter = invitation_filter.value if invitation_filter else "default"
    return InvitationListInput(
        context_id="invitation-tests",
        request_id=f"{direction.value}-{selected_filter}",
        direction=direction,
        invitation_filter=invitation_filter,
    )


async def _collect(
    page: Page,
    *,
    html: str,
    request: InvitationListInput,
    path: str,
    max_scroll_rounds: int = 4,
    result_limit: int | None = None,
) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
    fixture_browser = InvitationFixtureBrowser(page, {path: html})
    adapter = InvitationListPage(
        cast(BrowserManager, fixture_browser),
        max_scroll_rounds=max_scroll_rounds,
    )
    return await adapter.collect(request, result_limit=result_limit)


def test_fixture_manifest_records_sanitized_current_selector_provenance() -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))

    assert manifest == {
        "provenance": "mock_verified",
        "verified_at": "2026-08-15",
        "source_surface": "visible LinkedIn invitation manager",
        "contains_live_data": False,
        "contains_authentication_state": False,
        "received_bucket_selector": ('main [role="button"]:has(input[type="checkbox"]:checked)'),
        "received_bucket_option_selector": 'main [role="menu"] [role="menuitem"]',
        "received_category_selector": 'main [role="radio"][aria-checked]',
        "received_omitted_zero_filter_evidence": (
            "A missing category control while the current Focused selector remains exact "
            "represents that category's current zero-count state"
        ),
        "received_card_selector": (
            'main [data-testid="lazy-column"] [data-display-contents] > [role="listitem"]'
        ),
        "received_card_actions": [
            "Ignore an invitation to connect from {name}",
            "Accept {name}\N{RIGHT SINGLE QUOTATION MARK}s invitation",
        ],
        "sent_count_selector": 'main a[href$="/sent/CONNECTION/"]',
        "sent_omitted_people_empty_evidence": (
            "One idle empty lazy-column, no People-shaped control, no sent card root, "
            "no Withdraw action, and no tail control"
        ),
        "sent_card_selector": ('main [data-testid="lazy-column"] > [role="listitem"]'),
        "sent_card_action": "Withdraw invitation sent to {name}",
        "notes": (
            "Synthetic identities and content preserve only the sanitized current "
            "Focused/Other picker, conditionally rendered received radio filters, omitted "
            "empty Sent People control, Received/Sent card roots, and action-adjacent note "
            "structure."
        ),
    }


def test_invitation_input_defaults_are_direction_specific_and_fail_closed() -> None:
    assert _request().resolved_filter is InvitationFilter.ALL
    assert _request(direction=InvitationDirection.SENT).resolved_filter is InvitationFilter.PEOPLE
    assert (
        _request(invitation_filter=InvitationFilter.FOCUSED).resolved_filter
        is InvitationFilter.FOCUSED
    )
    assert (
        _request(invitation_filter=InvitationFilter.OTHER).resolved_filter is InvitationFilter.OTHER
    )

    with pytest.raises(ValidationError, match="Sent invitations support only"):
        _request(
            direction=InvitationDirection.SENT,
            invitation_filter=InvitationFilter.ALL,
        )
    with pytest.raises(ValidationError, match="People filter applies only"):
        _request(invitation_filter=InvitationFilter.PEOPLE)


@pytest.mark.asyncio
async def test_received_all_returns_every_invitation_entity_type(
    invitation_page: Page,
) -> None:
    values, coverage, captured_text, source_url = await _collect(
        invitation_page,
        html=_fixture("received-all.html"),
        request=_request(),
        path="/mynetwork/invitation-manager/received/",
    )
    assert len(values) == 8
    assert {item.primary_entity.entity_type for item in values} == set(InvitationEntityType)
    assert {item.invitation_type for item in values} == set(InvitationType)
    assert values[0].primary_entity.slug == "alex-member-"
    assert values[0].relationship_context == "12 mutual connections"
    assert values[0].note == "Thanks for considering this invitation."
    assert InvitationAvailableAction.MESSAGE in values[0].available_actions
    company = next(
        item for item in values if item.primary_entity.entity_type is InvitationEntityType.COMPANY
    )
    assert company.primary_entity.display_name == "Example Systems"
    assert company.inviter is not None
    assert company.inviter.display_name == "Casey Inviter"
    assert company.headline is None
    assert company.context == "Invited you to follow"
    assert coverage.advertised_count is None
    assert coverage.unique_count == 8
    assert coverage.view_counts == {
        InvitationFilter.FOCUSED: 4,
        InvitationFilter.OTHER: 3,
        InvitationFilter.VERIFIED: 1,
        InvitationFilter.MUTUAL_CONNECTIONS: 1,
        InvitationFilter.SAME_COMPANY: 1,
        InvitationFilter.SAME_SCHOOL: 1,
    }
    assert coverage.view_membership_count == 11
    assert coverage.overlap_count == 3
    assert coverage.result_count == 8
    assert coverage.max_results == 25
    assert coverage.neighboring_recommendation_count == 1
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert sum(coverage.invitation_type_counts.values()) == 8
    assert sum(coverage.entity_type_counts.values()) == 8
    assert all(
        evidence.quote in invitation.visible_text
        and str(evidence.source_url).rstrip("/") == source_url.rstrip("/")
        and evidence.captured_at == coverage.captured_at
        for invitation in values
        for evidence in invitation.evidence
    )
    assert "Focused (4)" in captured_text
    assert "Other (3)" in captured_text
    assert "Mutual Connections (1)" in captured_text
    assert "Recommended Member" not in captured_text


@pytest.mark.parametrize(
    ("invitation_filter", "expected_count"),
    [
        (InvitationFilter.FOCUSED, 4),
        (InvitationFilter.OTHER, 3),
    ],
)
@pytest.mark.asyncio
async def test_current_received_buckets_can_be_selected_explicitly(
    invitation_page: Page,
    invitation_filter: InvitationFilter,
    expected_count: int,
) -> None:
    values, coverage, captured_text, _ = await _collect(
        invitation_page,
        html=_fixture("received-all.html"),
        request=_request(invitation_filter=invitation_filter),
        path="/mynetwork/invitation-manager/received/",
    )

    assert len(values) == expected_count
    assert coverage.invitation_filter is invitation_filter
    assert coverage.view_counts == {invitation_filter: expected_count}
    assert coverage.advertised_count == expected_count
    assert coverage.unique_count == expected_count
    assert coverage.view_membership_count == expected_count
    assert coverage.overlap_count == 0
    assert _COUNT_LABELS[invitation_filter] in captured_text


@pytest.mark.asyncio
async def test_same_company_can_invite_to_two_distinct_current_newsletters(
    invitation_page: Page,
) -> None:
    def newsletter_card(name: str, newsletter_id: str) -> str:
        return f"""
          <div><div><div data-display-contents="true">
            <div role="listitem">
              <p>Newsletter • Monthly</p>
              <p>
                <a href="/company/example-cloud/"><strong>Example Cloud</strong></a>
                invited you to subscribe to
                <a href="/newsletters/{newsletter_id}/"><strong>{name}</strong></a>
              </p>
              <div><button aria-label="Ignore invitation for {name}">Ignore</button></div>
              <div><button aria-label="Accept invitation for {name}">Accept</button></div>
            </div>
          </div></div></div>
        """

    html = f"""
      <html><body><main>
        <div role="button" aria-expanded="false" tabindex="0">
          <input type="checkbox" checked />
          Focused (2)
        </div>
        <div data-testid="lazy-column">
          {newsletter_card("Engineering Weekly", "engineering-weekly-101")}
          {newsletter_card("Security Monthly", "security-monthly-202")}
        </div>
      </main></body></html>
    """

    values, coverage, _, _ = await _collect(
        invitation_page,
        html=html,
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
    )

    assert len({item.invitation_ref for item in values}) == coverage.unique_count == 2
    assert [item.primary_entity.entity_type for item in values] == [
        InvitationEntityType.NEWSLETTER,
        InvitationEntityType.NEWSLETTER,
    ]
    assert [item.primary_entity.slug for item in values] == [
        "engineering-weekly-101",
        "security-monthly-202",
    ]
    assert all(
        item.inviter is not None
        and item.inviter.entity_type is InvitationEntityType.COMPANY
        and item.inviter.slug == "example-cloud"
        for item in values
    )


@pytest.mark.asyncio
async def test_sent_people_uses_the_distinct_current_direct_card_root(
    invitation_page: Page,
) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("sent-people.html"),
        request=_request(direction=InvitationDirection.SENT),
        path="/mynetwork/invitation-manager/sent/",
    )
    assert [item.primary_entity.slug for item in values] == [
        "jordan-sent-",
        "morgan-sent",
    ]
    assert all(item.available_actions == (InvitationAvailableAction.WITHDRAW,) for item in values)
    assert values[1].note == "Thanks for considering my invitation."
    assert values[0].sent_or_received_at_text == "Sent 2 weeks ago"
    assert coverage.invitation_filter is InvitationFilter.PEOPLE
    assert coverage.view_counts == {InvitationFilter.PEOPLE: 2}
    assert coverage.unique_count == 2


@pytest.mark.asyncio
async def test_received_all_reconciles_category_controls_omitted_at_zero(
    invitation_page: Page,
) -> None:
    values, coverage, captured_text, _ = await _collect(
        invitation_page,
        html=_fixture("received-omitted-zero-filters.html"),
        request=_request(),
        path="/mynetwork/invitation-manager/received/",
    )

    assert [item.primary_entity.slug for item in values] == ["current-member"]
    assert coverage.view_counts == {
        InvitationFilter.FOCUSED: 1,
        InvitationFilter.OTHER: 0,
        InvitationFilter.VERIFIED: 0,
        InvitationFilter.MUTUAL_CONNECTIONS: 0,
        InvitationFilter.SAME_COMPANY: 0,
        InvitationFilter.SAME_SCHOOL: 0,
    }
    assert coverage.unadvertised_empty_views == (
        InvitationFilter.VERIFIED,
        InvitationFilter.MUTUAL_CONNECTIONS,
        InvitationFilter.SAME_COMPANY,
        InvitationFilter.SAME_SCHOOL,
    )
    assert coverage.advertised_count is None
    assert coverage.view_membership_count == coverage.unique_count == 1
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "Focused (1)" in captured_text
    assert "Other (0)" in captured_text
    assert "Verified (0)" not in captured_text


@pytest.mark.parametrize(
    "invitation_filter",
    [
        InvitationFilter.VERIFIED,
        InvitationFilter.MUTUAL_CONNECTIONS,
        InvitationFilter.SAME_COMPANY,
        InvitationFilter.SAME_SCHOOL,
    ],
)
@pytest.mark.asyncio
async def test_explicit_omitted_received_category_returns_proved_empty_view(
    invitation_page: Page,
    invitation_filter: InvitationFilter,
) -> None:
    values, coverage, captured_text, _ = await _collect(
        invitation_page,
        html=_fixture("received-omitted-zero-filters.html"),
        request=_request(invitation_filter=invitation_filter),
        path="/mynetwork/invitation-manager/received/",
    )

    assert values == ()
    assert coverage.advertised_count is None
    assert coverage.view_counts == {invitation_filter: 0}
    assert coverage.unadvertised_empty_views == (invitation_filter,)
    assert coverage.view_membership_count == coverage.unique_count == 0
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert captured_text == "Focused (1)"


@pytest.mark.asyncio
async def test_sent_people_control_omission_requires_stable_empty_column_evidence(
    invitation_page: Page,
) -> None:
    values, coverage, captured_text, _ = await _collect(
        invitation_page,
        html=_fixture("sent-omitted-empty-people.html"),
        request=_request(direction=InvitationDirection.SENT),
        path="/mynetwork/invitation-manager/sent/",
    )

    assert values == ()
    assert coverage.advertised_count is None
    assert coverage.view_counts == {InvitationFilter.PEOPLE: 0}
    assert coverage.unadvertised_empty_views == (InvitationFilter.PEOPLE,)
    assert coverage.view_membership_count == coverage.unique_count == 0
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert captured_text == "Manage invitations"


@pytest.mark.asyncio
async def test_sent_people_control_omission_with_a_card_fails_closed(
    invitation_page: Page,
) -> None:
    html = _fixture("sent-omitted-empty-people.html").replace(
        '<div data-testid="lazy-column" data-component-type="LazyColumn"></div>',
        """
        <div data-testid="lazy-column" data-component-type="LazyColumn">
          <div role="listitem">
            <a href="/in/unadvertised-sent/">Unadvertised Sent</a>
            <button aria-label="Withdraw invitation sent to Unadvertised Sent">
              Withdraw
            </button>
          </div>
        </div>
        """,
    )

    with pytest.raises(ParserDriftError, match=r"cannot prove.*People view empty"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(direction=InvitationDirection.SENT),
            path="/mynetwork/invitation-manager/sent/",
        )


@pytest.mark.asyncio
async def test_omitted_category_with_changed_control_shape_fails_closed(
    invitation_page: Page,
) -> None:
    html = _fixture("received-omitted-zero-filters.html").replace(
        '<div id="focused-column" data-testid="lazy-column">',
        """
        <div role="radio" aria-checked="false">Verified</div>
        <div id="focused-column" data-testid="lazy-column">
        """,
    )

    with pytest.raises(ParserDriftError, match="changed verified filter shape"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(invitation_filter=InvitationFilter.VERIFIED),
            path="/mynetwork/invitation-manager/received/",
        )


@pytest.mark.parametrize(
    "invitation_filter",
    [
        InvitationFilter.VERIFIED,
        InvitationFilter.MUTUAL_CONNECTIONS,
        InvitationFilter.SAME_COMPANY,
        InvitationFilter.SAME_SCHOOL,
    ],
)
@pytest.mark.asyncio
async def test_every_current_received_radio_filter_uses_its_exact_visible_count(
    invitation_page: Page,
    invitation_filter: InvitationFilter,
) -> None:
    values, coverage, _, source_url = await _collect(
        invitation_page,
        html=_fixture("received-filters.html"),
        request=_request(invitation_filter=invitation_filter),
        path="/mynetwork/invitation-manager/received/",
    )

    assert len(values) == 1
    assert coverage.invitation_filter is invitation_filter
    assert coverage.view_counts == {invitation_filter: 1}
    assert coverage.advertised_count == 1
    assert coverage.unique_count == 1
    assert urlsplit(source_url).path == "/mynetwork/invitation-manager/received/"


@pytest.mark.asyncio
async def test_zero_advertised_count_is_the_only_successful_empty_inventory(
    invitation_page: Page,
) -> None:
    values, coverage, captured_text, _ = await _collect(
        invitation_page,
        html=_fixture("received-empty.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
    )

    assert values == ()
    assert coverage.unique_count == coverage.advertised_count == 0
    assert coverage.scroll_rounds == 0
    assert coverage.view_counts == {InvitationFilter.FOCUSED: 0}
    assert captured_text == "Focused (0)"


@pytest.mark.asyncio
async def test_loading_pause_never_counts_as_end_of_list(invitation_page: Page) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("received-delayed-batches.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
        max_scroll_rounds=3,
    )
    assert [item.primary_entity.slug for item in values] == [
        "first-delayed",
        "second-delayed",
        "third-delayed",
    ]
    assert coverage.scroll_rounds == 2


@pytest.mark.asyncio
async def test_virtualized_same_size_windows_accumulate_one_complete_inventory(
    invitation_page: Page,
) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("received-virtualized.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
        max_scroll_rounds=3,
    )
    assert [item.primary_entity.slug for item in values] == [
        "first-window",
        "second-window",
        "third-window",
    ]
    assert coverage.unique_count == 3
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE


@pytest.mark.asyncio
async def test_one_count_change_discards_the_partial_scan_and_restarts(
    invitation_page: Page,
) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("received-count-changes-once.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
        max_scroll_rounds=3,
    )
    assert [item.primary_entity.slug for item in values] == [
        "stable-one",
        "stable-two",
        "stable-three",
    ]
    assert coverage.collection_attempts == 2
    assert coverage.advertised_count == 3
    assert coverage.unique_count == 3


@pytest.mark.asyncio
async def test_end_copy_and_idle_bottom_return_an_honest_safety_bound(
    invitation_page: Page,
) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("received-count-mismatch.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
        max_scroll_rounds=2,
    )

    assert [item.primary_entity.slug for item in values] == ["only-rendered"]
    assert coverage.advertised_count == 2
    assert coverage.unique_count == 1
    assert coverage.stop_reason is StopReason.SAFETY_BOUND


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("received-parser-drift.html", "card-root contract"),
        ("received-identity-mismatch.html", "conflicts with its visible profile"),
    ],
)
@pytest.mark.asyncio
async def test_old_or_identity_ambiguous_dom_fails_closed(
    invitation_page: Page,
    fixture_name: str,
    message: str,
) -> None:
    with pytest.raises(ParserDriftError, match=message):
        await _collect(
            invitation_page,
            html=_fixture(fixture_name),
            request=_request(invitation_filter=InvitationFilter.FOCUSED),
            path="/mynetwork/invitation-manager/received/",
        )


@pytest.mark.asyncio
async def test_missing_or_ambiguous_advertised_count_fails_closed(
    invitation_page: Page,
) -> None:
    html = _fixture("received-filters.html").replace("Focused (1)", "Priority (1)")
    with pytest.raises(ParserDriftError, match="Focused/Other selector"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(invitation_filter=InvitationFilter.FOCUSED),
            path="/mynetwork/invitation-manager/received/",
        )


@pytest.mark.asyncio
async def test_identical_virtualized_render_copies_are_deduplicated(
    invitation_page: Page,
) -> None:
    card = """
      <div><div><div data-display-contents="true">
        <div role="listitem">
          <a href="/in/duplicate-member/"><strong>Duplicate Member</strong></a>
          <button aria-label="Accept Duplicate Member&rsquo;s invitation">Accept</button>
        </div>
      </div></div></div>
    """
    html = f"""
      <html><body><main>
        <div role="button" aria-expanded="false" tabindex="0">
          <input type="checkbox" checked />
          Focused (1)
        </div>
        <div data-testid="lazy-column">{card}{card}</div>
      </main></body></html>
    """

    values, coverage, _, _ = await _collect(
        invitation_page,
        html=html,
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
    )

    assert len(values) == coverage.unique_count == 1
    assert values[0].primary_entity.slug == "duplicate-member"


@pytest.mark.asyncio
async def test_conflicting_virtualized_render_copies_fail_closed(
    invitation_page: Page,
) -> None:
    def card(headline: str) -> str:
        return f"""
          <div><div><div data-display-contents="true">
            <div role="listitem">
              <a href="/in/duplicate-member/"><strong>Duplicate Member</strong></a>
              <p>{headline}</p>
              <button aria-label="Accept Duplicate Member&rsquo;s invitation">Accept</button>
            </div>
          </div></div></div>
        """

    html = f"""
      <html><body><main>
        <div role="button" aria-expanded="false" tabindex="0">
          <input type="checkbox" checked />
          Focused (1)
        </div>
        <div data-testid="lazy-column">{card("Role One")}{card("Role Two")}</div>
      </main></body></html>
    """

    with pytest.raises(ParserDriftError, match="conflicting visible data"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(invitation_filter=InvitationFilter.FOCUSED),
            path="/mynetwork/invitation-manager/received/",
        )


@pytest.mark.asyncio
async def test_conflicting_copies_across_current_received_views_fail_closed(
    invitation_page: Page,
) -> None:
    html = _fixture("received-all.html").replace(
        "category.hidden = false;",
        """
            category.hidden = false;
            category.querySelector("p").textContent =
              radio.textContent.includes("Mutual")
                ? "Conflicting member context"
                : "Visible member for the selected filter";
        """,
    )

    with pytest.raises(ParserDriftError, match="conflicting data across"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(),
            path="/mynetwork/invitation-manager/received/",
        )


@pytest.mark.asyncio
async def test_live_traversal_stops_at_the_requested_result_limit(
    invitation_page: Page,
) -> None:
    values, coverage, _, _ = await _collect(
        invitation_page,
        html=_fixture("received-virtualized.html"),
        request=_request(invitation_filter=InvitationFilter.FOCUSED),
        path="/mynetwork/invitation-manager/received/",
        max_scroll_rounds=3,
        result_limit=2,
    )

    assert [item.primary_entity.slug for item in values] == [
        "first-window",
        "second-window",
    ]
    assert coverage.advertised_count == 3
    assert coverage.unique_count == coverage.result_count == coverage.max_results == 2
    assert coverage.stop_reason is StopReason.RESULT_LIMIT


@pytest.mark.asyncio
async def test_repeated_advertised_count_change_requires_a_fresh_call(
    invitation_page: Page,
) -> None:
    html = """
      <html><body>
        <main id="main" style="height: 100px; overflow-y: scroll">
          <div role="button" aria-expanded="false" tabindex="0">
            <input type="checkbox" checked />
            <span id="count">Focused (2)</span>
          </div>
          <div data-testid="lazy-column">
            <div><div><div data-display-contents="true">
              <div role="listitem">
                <a href="/in/changing-member/"><strong>Changing Member</strong></a>
                <button aria-label="Accept Changing Member&rsquo;s invitation">Accept</button>
              </div>
            </div></div></div>
          </div>
          <div style="height: 500px"></div>
        </main>
        <script>
          document.querySelector("#main").addEventListener("wheel", () => {
            document.querySelector("#count").textContent = "Focused (3)";
          }, {once: true});
        </script>
      </body></html>
    """

    with pytest.raises(BrowserUnavailableError, match="changed repeatedly"):
        await _collect(
            invitation_page,
            html=html,
            request=_request(invitation_filter=InvitationFilter.FOCUSED),
            path="/mynetwork/invitation-manager/received/",
            max_scroll_rounds=2,
        )
