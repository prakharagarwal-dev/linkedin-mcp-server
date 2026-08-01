from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import HttpUrl

import linkedin_mcp.browser.pages.connections as connection_pages
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.pages import ConnectionsListPage, InvitationActionPage
from linkedin_mcp.domain.models import (
    ActionDraft,
    ActionOutcome,
    ActionStatus,
    ActionTarget,
    ActionType,
    ConnectionsListInput,
    ConnectionsSortBy,
    InvitationAcceptPayload,
    InvitationAcceptPrepareInput,
    InvitationIgnorePayload,
    InvitationIgnorePrepareInput,
    InvitationSendPayload,
    InvitationSendPrepareInput,
    StopReason,
)
from linkedin_mcp.errors import (
    AuthenticationRequiredError,
    BrowserUnavailableError,
    InvalidTargetError,
    ParserDriftError,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
ACTION_FIXTURES = FIXTURES / "invitations" / "actions" / "latest"
INVITATION_REF = "invitation:ca598f6086a20bb05af6bfe8"


@pytest.fixture(autouse=True)
def _use_fast_synthetic_collection_clock(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connection_pages, "_SCROLL_PROGRESS_POLL_DELAY_MS", 25)


class ConnectionFixtureBrowser:
    def __init__(self, page: Page, fixtures_by_path: dict[str, str]) -> None:
        self._page = page
        self._fixtures_by_path = fixtures_by_path
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        matching_paths = sorted(
            (path for path in self._fixtures_by_path if path in url),
            key=len,
            reverse=True,
        )
        if not matching_paths:
            raise ValueError(f"No synthetic connection fixture is registered for {url}.")
        fixture = self._fixtures_by_path[matching_paths[0]]

        async def fulfill(route: Route) -> None:
            await route.fulfill(status=200, content_type="text/html", body=fixture)

        await page.route(url, fulfill, times=1)
        await page.goto(url, wait_until="domcontentloaded")
        self.navigations.append(url)

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        await control.click()
        await page.wait_for_timeout(10)

    async def assert_safe(self, page: Page) -> None:
        del page


class FailingConnectionClickBrowser(ConnectionFixtureBrowser):
    def __init__(
        self,
        page: Page,
        fixtures_by_path: dict[str, str],
        *,
        fail_pattern: str,
        error: Exception | None = None,
    ) -> None:
        super().__init__(page, fixtures_by_path)
        self._fail_pattern = fail_pattern.casefold()
        self._error = error or RuntimeError("simulated click interruption")

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        accessible_name = (
            await control.get_attribute("aria-label") or await control.inner_text()
        ).casefold()
        if self._fail_pattern in accessible_name:
            raise self._error
        await super().click_visible_control(page, control)


class ReloadFailingConnectionBrowser(ConnectionFixtureBrowser):
    def __init__(
        self,
        page: Page,
        fixtures_by_path: dict[str, str],
        *,
        error: Exception,
    ) -> None:
        super().__init__(page, fixtures_by_path)
        self._error = error

    async def navigate(self, page: Page, url: str) -> None:
        if self.navigations:
            raise self._error
        await super().navigate(page, url)


class SequencedConnectionFixtureBrowser(ConnectionFixtureBrowser):
    def __init__(self, page: Page, fixtures: tuple[str, ...]) -> None:
        if not fixtures:
            raise ValueError("A sequenced connection fixture requires at least one page.")
        super().__init__(page, {"/in/jane-doe/": fixtures[0]})
        self._fixtures = fixtures

    async def navigate(self, page: Page, url: str) -> None:
        fixture_index = min(len(self.navigations), len(self._fixtures) - 1)
        self._fixtures_by_path["/in/jane-doe/"] = self._fixtures[fixture_index]
        await super().navigate(page, url)


def _draft(
    action_type: ActionType,
    payload: InvitationSendPayload | InvitationAcceptPayload | InvitationIgnorePayload,
    *,
    name: str = "Jane Doe",
) -> ActionDraft:
    now = datetime.now(UTC)
    return ActionDraft(
        action_id=str(uuid.uuid4()),
        action_type=action_type,
        target=ActionTarget(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            display_name=name,
            invitation_ref=(
                None
                if action_type is ActionType.INVITATION_SEND
                else payload.invitation_ref
                if isinstance(payload, (InvitationAcceptPayload, InvitationIgnorePayload))
                else None
            ),
        ),
        payload=payload,
        payload_hash="a" * 64,
        status=ActionStatus.EXECUTING,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _invite_draft(note: str | None = "Hello Jane", *, name: str = "Jane Doe") -> ActionDraft:
    return _draft(
        ActionType.INVITATION_SEND,
        InvitationSendPayload(note=note),
        name=name,
    )


def _accept_draft(
    invitation_ref: str = INVITATION_REF,
    *,
    name: str = "Jane Doe",
) -> ActionDraft:
    return _draft(
        ActionType.INVITATION_ACCEPT,
        InvitationAcceptPayload(invitation_ref=invitation_ref),
        name=name,
    )


def _ignore_draft(
    invitation_ref: str = INVITATION_REF,
    *,
    name: str = "Jane Doe",
) -> ActionDraft:
    return _draft(
        ActionType.INVITATION_IGNORE,
        InvitationIgnorePayload(invitation_ref=invitation_ref),
        name=name,
    )


@pytest.mark.timeout(20)
async def test_exact_connection_lookup_returns_visible_identity_and_image() -> None:
    html = (FIXTURES / "connections-list-current.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConnectionsListPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(
                    page,
                    {"/mynetwork/invite-connect/connections/": html},
                ),
            ),
            max_scroll_rounds=1,
        )
        try:
            connection, image_src = await adapter.find_exact(
                page,
                profile_slug="jane-doe",
                query="Jane Doe",
            )
            with pytest.raises(InvalidTargetError, match="bounded Connections"):
                await adapter.find_exact(
                    page,
                    profile_slug="missing-person",
                    query="Missing Person",
                )
        finally:
            await browser.close()

    assert connection.profile_slug == "jane-doe"
    assert connection.headline == "Staff Engineer at Acme Cloud"
    assert image_src == "https://media.example.com/jane.jpg"


@pytest.mark.timeout(20)
async def test_connections_read_delayed_tail_and_trailing_hyphen_slugs() -> None:
    html = (FIXTURES / "connections-list-infinite-scroll-current.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConnectionsListPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(
                    page,
                    {"/mynetwork/invite-connect/connections/": html},
                ),
            ),
            max_scroll_rounds=5,
        )
        try:
            connections, coverage, captured_text, _ = await adapter.collect(
                ConnectionsListInput(
                    context_id="connections-context",
                    request_id="connections-infinite-scroll",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert [connection.profile_slug for connection in connections] == [
        "jane-doe",
        "alex-lee",
        "sam-kim",
        "morgan-ellis-",
        "riley-quinn--",
        "jordan-lee-",
    ]
    assert 2 <= coverage.rounds_visited <= 4
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "Jordan Lee" in captured_text


@pytest.mark.timeout(20)
async def test_connections_finish_at_live_stable_nested_bottom_without_end_copy() -> None:
    html = (FIXTURES / "connections-list-live-terminal-current.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConnectionsListPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(
                    page,
                    {"/mynetwork/invite-connect/connections/": html},
                ),
            ),
            max_scroll_rounds=8,
        )
        try:
            connections, coverage, captured_text, _ = await adapter.collect(
                ConnectionsListInput(
                    context_id="connections-context",
                    request_id="connections-live-terminal",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert [connection.profile_slug for connection in connections][-3:] == [
        "morgan-ellis-",
        "riley-quinn--",
        "jordan-lee-",
    ]
    assert 5 <= coverage.rounds_visited <= 8
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "No more connections" not in captured_text


@pytest.mark.timeout(20)
async def test_connections_detect_virtualized_same_count_replacement() -> None:
    html = (FIXTURES / "connections-list-virtualized-current.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConnectionsListPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(
                    page,
                    {"/mynetwork/invite-connect/connections/": html},
                ),
            ),
            max_scroll_rounds=5,
        )
        try:
            connections, coverage, captured_text, _ = await adapter.collect(
                ConnectionsListInput(
                    context_id="connections-context",
                    request_id="connections-virtualized",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert [connection.profile_slug for connection in connections] == [
        "jane-doe",
        "tail-member-",
    ]
    assert 2 <= coverage.rounds_visited <= 4
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "Tail Member" in captured_text


def test_latest_connection_and_invitation_fixtures_record_live_selector_provenance() -> None:
    list_manifest = json.loads((FIXTURES / "connections" / "latest" / "manifest.json").read_text())
    action_manifest = json.loads((ACTION_FIXTURES / "manifest.json").read_text())

    assert list_manifest["provenance"] == "mock_verified"
    assert list_manifest["verified_at"] == "2026-07-29"
    assert (
        list_manifest["list_card_selector"]
        == 'main [data-testid="lazy-column"] > [data-display-contents]'
    )
    assert list_manifest["observed_query_parameters"]["followers_of"] == "followerOf"
    assert action_manifest["provenance"] == "mock_verified"
    assert action_manifest["verified_at"] == "2026-07-30"
    assert action_manifest["contains_live_data"] is False
    assert action_manifest["send_profile_control"] == {
        "role": "button",
        "accessible_name": "Invite {name} to connect",
    }
    assert action_manifest["send_note_dialog"]["visible_counter"] == "0/200"
    assert action_manifest["send_execution_contract"] == {
        "pre_click_checks": [
            "exact note textbox value",
            "exact visible character counter",
            "enabled and Playwright-actionable Send control",
        ],
        "success": "A fresh exact-profile read visibly shows Pending.",
        "failure": "A fresh exact-profile read still visibly shows Connect.",
        "uncertain": "The final click or fresh exact-profile state cannot be verified.",
    }
    assert "fresh exact-profile" in action_manifest["postconditions"]["send"]
    assert "Connect for failure" in action_manifest["postconditions"]["send"]
    assert (
        action_manifest["incoming_profile_controls"]["ignore"]
        == "Ignore {name}\N{RIGHT SINGLE QUOTATION MARK}s request to connect"
    )


@pytest.mark.timeout(20)
async def test_connections_list_uses_latest_visible_sort_and_card_contract() -> None:
    html = (FIXTURES / "connections" / "latest" / "list.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConnectionsListPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(
                    page,
                    {"/mynetwork/invite-connect/connections/": html},
                ),
            ),
            max_scroll_rounds=5,
        )
        try:
            connections, coverage, captured_text, source_url = await adapter.collect(
                ConnectionsListInput(
                    context_id="connections-context",
                    request_id="connections-1",
                    sort_by=ConnectionsSortBy.FIRST_NAME,
                    page_size=4,
                )
            )
        finally:
            await browser.close()

    assert [connection.profile_slug for connection in connections] == [
        "alex-rivera",
        "casey-lee",
        "jordan-ng-",
    ]
    assert coverage.sort_by is ConnectionsSortBy.FIRST_NAME
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "Connected 2 weeks ago" in captured_text
    assert source_url.endswith("/mynetwork/invite-connect/connections/")


@pytest.mark.timeout(20)
@pytest.mark.parametrize("note", [None, "Hello Jane"])
async def test_invite_prepare_inspects_current_dialog_without_sending(
    note: str | None,
) -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            capture = await adapter.prepare_send(
                InvitationSendPrepareInput(
                    context_id="connections-context",
                    request_id=f"prepare-invite-{note is not None}",
                    profile_slug="jane-doe",
                    note=note,
                )
            )
            pending_count = await page.get_by_role("button", name="Pending").count()
            textbox = page.get_by_role("textbox")
            textbox_value = (
                await textbox.input_value()
                if note is not None and await textbox.count() == 1
                else None
            )
        finally:
            await browser.close()

    assert capture.current_state == "connect_available"
    assert capture.target.display_name == "Jane Doe"
    assert pending_count == 0
    assert textbox_value == note
    expected_dialog = (
        "Add a note to your invitation" if note is not None else "Add a note to your invitation?"
    )
    assert expected_dialog in capture.captured_text


@pytest.mark.timeout(20)
async def test_invite_prepare_selects_current_identity_bound_button_among_recommendations() -> None:
    html = (
        (ACTION_FIXTURES / "send-profile.html")
        .read_text()
        .replace(
            "</main>",
            (
                '<button type="button" aria-label="Invite Other Person to connect">'
                "Connect</button></main>"
            ),
            1,
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            capture = await adapter.prepare_send(
                InvitationSendPrepareInput(
                    context_id="connections-context",
                    request_id="prepare-identity-bound-current-button",
                    profile_slug="jane-doe",
                )
            )
        finally:
            await browser.close()

    assert capture.current_state == "connect_available"
    assert capture.target.display_name == "Jane Doe"


@pytest.mark.timeout(20)
async def test_invite_prepare_waits_for_current_profile_action_hydration() -> None:
    html = (
        (ACTION_FIXTURES / "send-profile.html")
        .read_text()
        .replace('id="connect"', 'id="connect" hidden', 1)
        .replace(
            'const connect = document.querySelector("#connect");',
            (
                'const connect = document.querySelector("#connect");\n'
                "      window.setTimeout(() => { connect.hidden = false; }, 500);"
            ),
            1,
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            capture = await adapter.prepare_send(
                InvitationSendPrepareInput(
                    context_id="connections-context",
                    request_id="prepare-after-profile-action-hydration",
                    profile_slug="jane-doe",
                )
            )
        finally:
            await browser.close()

    assert capture.current_state == "connect_available"
    assert capture.target.display_name == "Jane Doe"


@pytest.mark.timeout(20)
@pytest.mark.parametrize("note", [None, "Hello Jane"])
async def test_invite_execute_uses_current_dialog_and_exact_pending_postcondition(
    note: str | None,
) -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = ConnectionFixtureBrowser(page, {"/in/jane-doe/": html})
        adapter = InvitationActionPage(cast(BrowserManager, fixture_browser))
        try:
            result = await adapter.execute_send(_invite_draft(note))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "pending_sent"
    assert "Pending" in result.captured_text
    assert len(fixture_browser.navigations) == 2


@pytest.mark.timeout(20)
async def test_invite_fails_closed_for_current_dialog_drift_and_changed_target() -> None:
    base = (ACTION_FIXTURES / "send-profile.html").read_text()
    wrong_link = base.replace(
        "Invite Jane Doe to connect",
        "Invite Jane Roe to connect",
    )
    no_counter = base.replace('<span id="note-counter">0/200</span>', "")
    stale_counter = base.replace(
        'data-counter-mode="accurate"',
        'data-counter-mode="stale"',
    )
    disabled_send = base.replace(
        'id="send-without-note"\n        type="button"',
        'id="send-without-note"\n        type="button"\n        disabled',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            wrong_adapter = InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": wrong_link}),
                )
            )
            with pytest.raises(InvalidTargetError, match="connect_unavailable"):
                await wrong_adapter.prepare_send(
                    InvitationSendPrepareInput(
                        context_id="connections-context",
                        request_id="wrong-link",
                        profile_slug="jane-doe",
                    )
                )

            counter_adapter = InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": no_counter}),
                )
            )
            with pytest.raises(ParserDriftError, match="character limit"):
                await counter_adapter.prepare_send(
                    InvitationSendPrepareInput(
                        context_id="connections-context",
                        request_id="missing-counter",
                        profile_slug="jane-doe",
                        note="Hello Jane",
                    )
                )

            with pytest.raises(ParserDriftError, match="did not visibly commit"):
                await InvitationActionPage(
                    cast(
                        BrowserManager,
                        ConnectionFixtureBrowser(page, {"/in/jane-doe/": stale_counter}),
                    )
                ).prepare_send(
                    InvitationSendPrepareInput(
                        context_id="connections-context",
                        request_id="stale-counter",
                        profile_slug="jane-doe",
                        note="Hello Jane",
                    )
                )

            with pytest.raises(ParserDriftError, match="not actionable"):
                await InvitationActionPage(
                    cast(
                        BrowserManager,
                        ConnectionFixtureBrowser(page, {"/in/jane-doe/": disabled_send}),
                    )
                ).prepare_send(
                    InvitationSendPrepareInput(
                        context_id="connections-context",
                        request_id="disabled-send",
                        profile_slug="jane-doe",
                    )
                )

            changed = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(
                        page,
                        {"/in/jane-doe/": base.replace("<h1>Jane Doe</h1>", "<h1>Jane Roe</h1>")},
                    ),
                )
            ).execute_send(_invite_draft())
        finally:
            await browser.close()

    assert changed.outcome is ActionOutcome.FAILED
    assert changed.final_state == "target_identity_changed"


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    ("fixture_change", "note", "message"),
    [
        (
            ("Add a note to your invitation?", "How do you know Jane Doe?"),
            None,
            "relationship choice",
        ),
        (
            ('aria-label="Send without a note"', 'aria-label="Submit invitation"'),
            None,
            "Send without a note control",
        ),
        (
            ('aria-label="Add a note"', 'aria-label="Personalize invitation"'),
            "Hello Jane",
            "personalized note",
        ),
        (
            ('<span id="note-counter">0/200</span>', '<span id="note-counter">0/5</span>'),
            "Hello Jane",
            "exceeds",
        ),
        (
            (
                '<span id="note-counter">0/200</span>',
                '<span id="note-counter">0/200</span><p>1/200</p>',
            ),
            "Hello Jane",
            "character counter",
        ),
        (
            (
                '<textarea placeholder="Ex: We know each other from…"></textarea>',
                (
                    '<textarea maxlength="not-a-number" '
                    'placeholder="Ex: We know each other from…"></textarea>'
                ),
            ),
            "Hello Jane",
            "invalid invitation-note maxlength",
        ),
        (
            ('aria-label="Send invitation"', 'aria-label="Submit invitation"'),
            "Hello Jane",
            "Send invitation control",
        ),
        (
            (
                'id="send-without-note"\n        type="button"',
                (
                    'id="send-without-note"\n        type="button"\n'
                    '        style="pointer-events: none"'
                ),
            ),
            None,
            "actionability checks",
        ),
    ],
    ids=[
        "relationship-required",
        "missing-send-without-note",
        "personalized-note-unavailable",
        "current-limit-smaller",
        "ambiguous-current-counter",
        "invalid-maxlength",
        "missing-note-send",
        "actionability-race",
    ],
)
async def test_invite_prepare_covers_current_dialog_safety_failures(
    fixture_change: tuple[str, str],
    note: str | None,
    message: str,
) -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text().replace(*fixture_change)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            with pytest.raises((InvalidTargetError, ParserDriftError), match=message):
                await adapter.prepare_send(
                    InvitationSendPrepareInput(
                        context_id="connections-context",
                        request_id="prepare-safety-failure",
                        profile_slug="jane-doe",
                        note=note,
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_invite_click_interruption_is_uncertain_and_fresh_connect_is_failed() -> None:
    base = (ACTION_FIXTURES / "send-profile.html").read_text()
    not_sent = base.replace('data-send-outcome="pending"', 'data-send-outcome="connect"')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            interrupted = await InvitationActionPage(
                cast(
                    BrowserManager,
                    FailingConnectionClickBrowser(
                        page,
                        {"/in/jane-doe/": base},
                        fail_pattern="send invitation",
                    ),
                )
            ).execute_send(_invite_draft())
            failed = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": not_sent}),
                )
            ).execute_send(_invite_draft(note=None))
        finally:
            await browser.close()

    assert interrupted.outcome is ActionOutcome.UNCERTAIN
    assert interrupted.performed is None
    assert "did not complete" in interrupted.detail
    assert failed.outcome is ActionOutcome.FAILED
    assert failed.performed is False
    assert failed.final_state == "invitation_not_sent"
    assert "still shows Connect" in failed.detail
    assert "Connect" in failed.captured_text


@pytest.mark.timeout(20)
async def test_invite_execute_reports_missing_dialog_and_typed_click_uncertainty() -> None:
    base = (ACTION_FIXTURES / "send-profile.html").read_text()
    missing_dialog = base.replace("inviteDialog.showModal();", "")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            no_dialog = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": missing_dialog}),
                )
            ).execute_send(_invite_draft())
            interrupted = await InvitationActionPage(
                cast(
                    BrowserManager,
                    FailingConnectionClickBrowser(
                        page,
                        {"/in/jane-doe/": base},
                        fail_pattern="send invitation",
                        error=BrowserUnavailableError("Synthetic typed click failure."),
                    ),
                )
            ).execute_send(_invite_draft())
        finally:
            await browser.close()

    assert no_dialog.outcome is ActionOutcome.FAILED
    assert no_dialog.performed is False
    assert no_dialog.final_state == "connection_dialog_unavailable"
    assert interrupted.outcome is ActionOutcome.UNCERTAIN
    assert interrupted.performed is None
    assert "Synthetic typed click failure" in interrupted.detail


@pytest.mark.timeout(20)
async def test_invite_final_click_authentication_failure_is_not_swallowed() -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            with pytest.raises(AuthenticationRequiredError):
                await InvitationActionPage(
                    cast(
                        BrowserManager,
                        FailingConnectionClickBrowser(
                            page,
                            {"/in/jane-doe/": html},
                            fail_pattern="send invitation",
                            error=AuthenticationRequiredError(),
                        ),
                    )
                ).execute_send(_invite_draft())
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_invite_execute_rejects_disabled_send_and_uncommitted_note_before_click() -> None:
    base = (ACTION_FIXTURES / "send-profile.html").read_text()
    disabled = base.replace(
        'id="send-invitation" type="button"',
        'id="send-invitation" type="button" disabled',
    )
    stale_counter = base.replace(
        'data-counter-mode="accurate"',
        'data-counter-mode="stale"',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            disabled_result = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": disabled}),
                )
            ).execute_send(_invite_draft())
            stale_result = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": stale_counter}),
                )
            ).execute_send(_invite_draft())
        finally:
            await browser.close()

    assert disabled_result.outcome is ActionOutcome.FAILED
    assert disabled_result.performed is False
    assert disabled_result.final_state == "invitation_send_not_actionable"
    assert stale_result.outcome is ActionOutcome.FAILED
    assert stale_result.performed is False
    assert stale_result.final_state == "invitation_note_not_committed"


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    ("html", "note", "final_state"),
    [
        (
            """
            <html><body><main>
              <h1>Jane Doe</h1><p>2nd degree connection</p>
            </main></body></html>
            """,
            None,
            "connect_unavailable",
        ),
        (
            (ACTION_FIXTURES / "send-profile.html")
            .read_text()
            .replace("Add a note to your invitation?", "How do you know Jane Doe?"),
            None,
            "relationship_confirmation_required",
        ),
        (
            (ACTION_FIXTURES / "send-profile.html")
            .read_text()
            .replace('aria-label="Add a note"', 'aria-label="Personalize invitation"'),
            "Hello Jane",
            "personalized_invitation_unavailable",
        ),
        (
            (ACTION_FIXTURES / "send-profile.html")
            .read_text()
            .replace(
                '<span id="note-counter">0/200</span>',
                '<span id="note-counter">0/5</span>',
            ),
            "Hello Jane",
            "invitation_note_too_long",
        ),
        (
            (ACTION_FIXTURES / "send-profile.html")
            .read_text()
            .replace('aria-label="Send invitation"', 'aria-label="Submit invitation"'),
            "Hello Jane",
            "invitation_send_unavailable",
        ),
        (
            (ACTION_FIXTURES / "send-profile.html")
            .read_text()
            .replace(
                'id="send-without-note"\n        type="button"',
                (
                    'id="send-without-note"\n        type="button"\n'
                    '        style="pointer-events: none"'
                ),
            ),
            None,
            "invitation_send_not_actionable",
        ),
    ],
    ids=[
        "connect-disappeared",
        "relationship-required",
        "personalized-note-unavailable",
        "current-limit-smaller",
        "send-control-drift",
        "actionability-race",
    ],
)
async def test_invite_execute_fails_before_dispatch_for_current_ui_safety_errors(
    html: str,
    note: str | None,
    final_state: str,
) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            result = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
                )
            ).execute_send(_invite_draft(note))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == final_state


@pytest.mark.timeout(20)
@pytest.mark.parametrize(
    ("profile_body", "final_state"),
    [
        (
            "<h1>Jane Doe</h1><p>2nd degree connection</p>"
            '<button aria-label="Pending">Pending</button>',
            "pending_sent",
        ),
        (
            "<h1>Jane Doe</h1><p>1st degree connection</p>"
            '<a href="/messaging/thread/new/" aria-label="Message Jane Doe">Message</a>',
            "already_connected",
        ),
    ],
)
async def test_invite_execute_is_a_verified_noop_for_existing_terminal_state(
    profile_body: str,
    final_state: str,
) -> None:
    html = f"<html><body><main>{profile_body}</main></body></html>"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            result = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
                )
            ).execute_send(_invite_draft())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is False
    assert result.final_state == final_state


@pytest.mark.timeout(20)
@pytest.mark.parametrize(
    ("reload_error", "detail"),
    [
        (
            BrowserUnavailableError("Synthetic fresh-profile read failed."),
            "fresh profile verification failed",
        ),
        (
            RuntimeError("Synthetic Playwright reload failure."),
            "could not be read",
        ),
    ],
    ids=["typed-browser-error", "unexpected-browser-error"],
)
async def test_invite_post_click_reload_failure_is_uncertain_with_retained_evidence(
    reload_error: Exception,
    detail: str,
) -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            result = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ReloadFailingConnectionBrowser(
                        page,
                        {"/in/jane-doe/": html},
                        error=reload_error,
                    ),
                )
            ).execute_send(_invite_draft())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert detail in result.detail
    assert "Jane Doe" in result.captured_text
    assert "Add a note to your invitation" in result.captured_text


@pytest.mark.timeout(20)
@pytest.mark.parametrize(
    ("fresh_profile_body", "detail"),
    [
        (
            "<h1>Jane Roe</h1><p>2nd degree connection</p>"
            '<button aria-label="Invite Jane Roe to connect">Connect</button>',
            "identity did not match",
        ),
        (
            "<h1>Jane Doe</h1><p>1st degree connection</p>"
            '<a href="/messaging/thread/new/" aria-label="Message Jane Doe">Message</a>',
            "observed state was already_connected",
        ),
    ],
    ids=["changed-identity", "neither-pending-nor-connect"],
)
async def test_invite_fresh_profile_ambiguous_state_is_uncertain(
    fresh_profile_body: str,
    detail: str,
) -> None:
    initial = (ACTION_FIXTURES / "send-profile.html").read_text()
    fresh = f"<html><body><main>{fresh_profile_body}</main></body></html>"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = SequencedConnectionFixtureBrowser(page, (initial, fresh))
        try:
            result = await InvitationActionPage(cast(BrowserManager, fixture_browser)).execute_send(
                _invite_draft()
            )
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "invitation_outcome_unknown"
    assert detail in result.detail
    assert len(fixture_browser.navigations) == 2


@pytest.mark.timeout(20)
async def test_invite_post_click_authentication_failure_is_not_swallowed() -> None:
    html = (ACTION_FIXTURES / "send-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            with pytest.raises(AuthenticationRequiredError):
                await InvitationActionPage(
                    cast(
                        BrowserManager,
                        ReloadFailingConnectionBrowser(
                            page,
                            {"/in/jane-doe/": html},
                            error=AuthenticationRequiredError(),
                        ),
                    )
                ).execute_send(_invite_draft())
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_accept_and_ignore_prepare_target_exact_current_profile_controls() -> None:
    html = (ACTION_FIXTURES / "incoming-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            accepted = await adapter.prepare_accept(
                InvitationAcceptPrepareInput(
                    context_id="connections-context",
                    request_id="prepare-accept",
                    profile_slug="jane-doe",
                )
            )
            ignored = await adapter.prepare_ignore(
                InvitationIgnorePrepareInput(
                    context_id="connections-context",
                    request_id="prepare-ignore",
                    profile_slug="jane-doe",
                )
            )
        finally:
            await browser.close()

    assert accepted.current_state == "received_invitation_pending"
    assert accepted.target.invitation_ref == INVITATION_REF
    assert ignored.target == accepted.target
    assert "Accept" in accepted.captured_text
    assert "Ignore" in ignored.captured_text
    assert accepted.source_url.path == "/in/jane-doe/"


@pytest.mark.timeout(20)
async def test_accept_execute_verifies_exact_profile_terminal_state_after_reload() -> None:
    html = (ACTION_FIXTURES / "incoming-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            result = await adapter.execute_accept(_accept_draft())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "connected"
    assert "1st degree connection" in result.captured_text


@pytest.mark.timeout(20)
async def test_ignore_execute_verifies_request_removed_without_connection_after_reload() -> None:
    html = (ACTION_FIXTURES / "incoming-profile.html").read_text()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = InvitationActionPage(
            cast(
                BrowserManager,
                ConnectionFixtureBrowser(page, {"/in/jane-doe/": html}),
            )
        )
        try:
            result = await adapter.execute_ignore(_ignore_draft())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "invitation_ignored"
    assert "2nd degree connection" in result.captured_text
    assert "1st degree connection" not in result.captured_text


@pytest.mark.timeout(20)
async def test_incoming_actions_fail_closed_for_missing_pair_identity_and_click_interruptions() -> (
    None
):
    base = (ACTION_FIXTURES / "incoming-profile.html").read_text()
    missing_pair = base.replace(
        'aria-label="Ignore Jane Doe\N{RIGHT SINGLE QUOTATION MARK}s request to connect"',
        'aria-label="Dismiss request"',
    )
    changed_identity = base.replace("<h1>Jane Doe</h1>", "<h1>Jane Roe</h1>")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            with pytest.raises(ParserDriftError, match="incomplete"):
                await InvitationActionPage(
                    cast(
                        BrowserManager,
                        ConnectionFixtureBrowser(page, {"/in/jane-doe/": missing_pair}),
                    )
                ).prepare_accept(
                    InvitationAcceptPrepareInput(
                        context_id="connections-context",
                        request_id="missing-pair",
                        profile_slug="jane-doe",
                    )
                )

            changed = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(page, {"/in/jane-doe/": changed_identity}),
                )
            ).execute_accept(_accept_draft())
            interrupted_accept = await InvitationActionPage(
                cast(
                    BrowserManager,
                    FailingConnectionClickBrowser(
                        page,
                        {"/in/jane-doe/": base},
                        fail_pattern="accept jane doe",
                    ),
                )
            ).execute_accept(_accept_draft())
            interrupted_ignore = await InvitationActionPage(
                cast(
                    BrowserManager,
                    FailingConnectionClickBrowser(
                        page,
                        {"/in/jane-doe/": base},
                        fail_pattern="ignore jane doe",
                    ),
                )
            ).execute_ignore(_ignore_draft())
        finally:
            await browser.close()

    assert changed.outcome is ActionOutcome.FAILED
    assert changed.final_state == "target_identity_changed"
    assert interrupted_accept.outcome is ActionOutcome.UNCERTAIN
    assert interrupted_accept.performed is None
    assert interrupted_ignore.outcome is ActionOutcome.UNCERTAIN
    assert interrupted_ignore.performed is None


@pytest.mark.timeout(20)
async def test_incoming_actions_require_their_distinct_fresh_profile_postconditions() -> None:
    base = (ACTION_FIXTURES / "incoming-profile.html").read_text()
    accept_removes_without_connecting = base.replace(
        'sessionStorage.setItem("mock-connection-request-state", "connected");',
        'sessionStorage.setItem("mock-connection-request-state", "ignored");',
    )
    ignore_creates_connection = base.replace(
        'sessionStorage.setItem("mock-connection-request-state", "ignored");',
        'sessionStorage.setItem("mock-connection-request-state", "connected");',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            accepted = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(
                        page,
                        {"/in/jane-doe/": accept_removes_without_connecting},
                    ),
                )
            ).execute_accept(_accept_draft())
            await page.evaluate("sessionStorage.clear()")
            ignored = await InvitationActionPage(
                cast(
                    BrowserManager,
                    ConnectionFixtureBrowser(
                        page,
                        {"/in/jane-doe/": ignore_creates_connection},
                    ),
                )
            ).execute_ignore(_ignore_draft())
        finally:
            await browser.close()

    assert accepted.outcome is ActionOutcome.UNCERTAIN
    assert accepted.final_state == "acceptance_outcome_unknown"
    assert ignored.outcome is ActionOutcome.UNCERTAIN
    assert ignored.final_state == "ignore_outcome_unknown"


@pytest.mark.asyncio
async def test_connection_action_payload_types_and_references_are_enforced() -> None:
    adapter = InvitationActionPage(cast(BrowserManager, object()))

    with pytest.raises(InvalidTargetError, match="invitation action payload"):
        await adapter.execute_send(_accept_draft())
    with pytest.raises(InvalidTargetError, match="acceptance action payload"):
        await adapter.execute_accept(_invite_draft())
    with pytest.raises(InvalidTargetError, match="ignore action payload"):
        await adapter.execute_ignore(_accept_draft())
    with pytest.raises(InvalidTargetError, match="acceptance payload does not match"):
        await adapter.execute_accept(_accept_draft("invitation:" + "f" * 24))
    with pytest.raises(InvalidTargetError, match="ignore payload does not match"):
        await adapter.execute_ignore(_ignore_draft("invitation:" + "f" * 24))
