from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import HttpUrl, ValidationError

import linkedin_mcp.tools.messaging._shared.pages as messaging_pages
from linkedin_mcp.app.assets import LocalAssetStore
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionOutcome,
    ActionTarget,
    ActionType,
    InvitationSendPayload,
    MessageGifInput,
    MessageSendPayload,
)
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools.messaging._shared.pages import (
    ConversationPage,
    ConversationSearchPage,
)
from linkedin_mcp.tools.messaging.conversation.get.evidence import source_from_conversation
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_input import (
    ConversationGetInput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_attachment_kind import (
    MessageAttachmentKind,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_direction import MessageDirection
from linkedin_mcp.tools.messaging.search.models.conversation_category import ConversationCategory
from linkedin_mcp.tools.messaging.search.models.conversation_filter import ConversationFilter
from linkedin_mcp.tools.messaging.search.models.conversation_search_input import (
    ConversationSearchInput,
)
from linkedin_mcp.tools.messaging.send.models.message_file_input import MessageFileInput
from linkedin_mcp.tools.messaging.send.models.message_send_input import MessageSendInput

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
MESSAGING_FIXTURES = FIXTURES / "messaging" / "latest"


class MessagingFixtureBrowser:
    def __init__(self, page: Page, html: str) -> None:
        self._page = page
        self._html = html

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        async def fulfill(route: Route) -> None:
            await route.fulfill(status=200, content_type="text/html", body=self._html)

        await page.route(url, fulfill, times=1)
        await page.goto(url)

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        await control.click()
        await page.wait_for_timeout(10)

    async def assert_safe(self, page: Page) -> None:
        del page


class RoutedMessagingFixtureBrowser(MessagingFixtureBrowser):
    def __init__(self, page: Page, fixtures_by_path: dict[str, str]) -> None:
        super().__init__(page, "")
        self._fixtures_by_path = fixtures_by_path

    async def navigate(self, page: Page, url: str) -> None:
        async def fulfill(route: Route) -> None:
            html = next(
                value for path, value in self._fixtures_by_path.items() if path in route.request.url
            )
            await route.fulfill(status=200, content_type="text/html", body=html)

        await page.route("**/*", fulfill, times=1)
        await page.goto(url, wait_until="domcontentloaded")


class PopupMessagingFixtureBrowser(MessagingFixtureBrowser):
    def __init__(self, page: Page, profile_html: str, thread_html: str) -> None:
        super().__init__(page, profile_html)
        self._thread_html = thread_html

    async def navigate(self, page: Page, url: str) -> None:
        html = self._thread_html if "/messaging/" in url else self._html

        async def fulfill(route: Route) -> None:
            await route.fulfill(
                status=200,
                content_type="text/html",
                body=html,
            )

        await page.route(url, fulfill, times=1)
        await page.goto(url)


class FailingMessageClickBrowser(MessagingFixtureBrowser):
    async def click_visible_control(self, page: Page, control: Locator) -> None:
        accessible_name = (
            await control.get_attribute("aria-label") or await control.inner_text()
        ).casefold()
        if accessible_name.startswith("send"):
            raise RuntimeError("simulated message click interruption")
        await super().click_visible_control(page, control)


class FailingGifClickBrowser(MessagingFixtureBrowser):
    async def click_visible_control(self, page: Page, control: Locator) -> None:
        classes = (await control.get_attribute("class") or "").split()
        accessible_name = (
            await control.get_attribute("aria-label") or await control.inner_text()
        ).casefold()
        if accessible_name == "celebration dance" or "tenor-gif__select-gif" in classes:
            raise RuntimeError("simulated GIF click interruption")
        await super().click_visible_control(page, control)


def _message_command(
    *,
    message: str = "Thanks for reaching out.",
    display_name: str = "Jane Doe",
    conversation_id: str | None = "thread-123",
) -> ActionCommand:
    return ActionCommand(
        action_type=ActionType.MESSAGE_SEND,
        target=ActionTarget(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            display_name=display_name,
            conversation_id=conversation_id,
        ),
        payload=MessageSendPayload(message=message),
    )


def _profile_message_html() -> str:
    return """
    <!doctype html>
    <html><body>
      <main>
        <div aria-label="Jane Doe profile card">
          <section aria-label="Jane Doe profile introduction">
            <h1>Jane Doe</h1>
            <p>1st degree connection</p>
          </section>
          <div aria-label="Jane Doe profile actions">
            <button id="profile-message" aria-label="Message Jane Doe">Message</button>
          </div>
        </div>
        <section aria-label="Highlights">
          <h2>Highlights</h2>
          <button aria-label="Message Jane Doe">Message</button>
        </section>
      </main>
      <aside id="profile-message-overlay" aria-label="Conversation with Jane Doe" hidden>
        <h2><a href="/in/jane-doe/">Jane Doe</a></h2>
        <ol id="profile-messages">
          <li class="msg-s-event-listitem">
            <span class="msg-s-message-group__name">Jane Doe</span>
            <p class="msg-s-event-listitem__body">Hello!</p>
          </li>
        </ol>
        <div id="profile-composer" contenteditable="true" role="textbox"
             aria-label="Write a message" maxlength="8000"></div>
        <button id="profile-send" aria-label="Send">Send</button>
      </aside>
      <script>
        const profileOverlay = document.querySelector("#profile-message-overlay");
        document.querySelector("#profile-message").addEventListener(
          "click",
          () => profileOverlay.hidden = false
        );
        document.querySelector("#profile-send").addEventListener("click", () => {
          const composer = document.querySelector("#profile-composer");
          const item = document.createElement("li");
          item.className = "msg-s-event-listitem";
          item.innerHTML =
            '<span class="msg-s-message-group__name">Current Member</span>' +
            '<p class="msg-s-event-listitem__body"></p>';
          item.querySelector("p").textContent = composer.innerText;
          document.querySelector("#profile-messages").appendChild(item);
          composer.innerText = "";
        });
      </script>
    </body></html>
    """


def _profile_message_thread_html() -> str:
    return """
    <!doctype html>
    <html><body>
      <main>
        <section aria-label="Jane Doe profile introduction">
          <h1>Jane Doe</h1>
          <p>1st degree connection</p>
          <button id="profile-message" aria-label="Message Jane Doe">Message</button>
        </section>
      </main>
      <script>
        document.querySelector("#profile-message").addEventListener("click", () => {
          history.pushState({}, "", "/messaging/thread/thread-from-profile/");
          document.querySelector("main").innerHTML = `
            <section aria-label="Conversation with Jane Doe">
              <h2><a href="/in/jane-doe/">Jane Doe</a></h2>
              <ol id="profile-thread-messages">
                <li class="msg-s-event-listitem">
                  <span class="msg-s-message-group__name">Jane Doe</span>
                  <p class="msg-s-event-listitem__body">Hello!</p>
                </li>
              </ol>
              <div id="profile-thread-composer" contenteditable="plaintext-only"
                   role="textbox" aria-label="Write a message" maxlength="8000"></div>
              <button id="profile-thread-send" aria-label="Send">Send</button>
            </section>
          `;
          document.querySelector("#profile-thread-send").addEventListener("click", () => {
            const composer = document.querySelector("#profile-thread-composer");
            const item = document.createElement("li");
            item.className = "msg-s-event-listitem";
            item.innerHTML =
              '<span class="msg-s-message-group__name">Current Member</span>' +
              '<p class="msg-s-event-listitem__body"></p>';
            item.querySelector("p").textContent = composer.innerText;
            document.querySelector("#profile-thread-messages").appendChild(item);
            composer.innerText = "";
          });
        });
      </script>
    </body></html>
    """


def _profile_message_popup_html() -> str:
    return """
    <!doctype html>
    <html><body>
      <main>
        <div aria-label="Jane Doe profile card">
          <section aria-label="Jane Doe profile introduction">
            <h1>Jane Doe</h1>
            <p>1st degree connection</p>
          </section>
          <div aria-label="Jane Doe profile actions">
            <a id="profile-message" aria-label="Message Jane Doe"
               href="/messaging/thread/thread-popup/" target="_blank">Message</a>
          </div>
        </div>
      </main>
    </body></html>
    """


def _profile_message_compose_profile_html() -> str:
    return _profile_message_popup_html().replace(
        "/messaging/thread/thread-popup/",
        (
            "/messaging/compose/?"
            "profileUrn=urn%3Ali%3Afsd_profile%3Aopaque-jane&"
            "recipient=opaque-jane&"
            "screenContext=NON_SELF_PROFILE_VIEW&"
            "interop=msgOverlay"
        ),
    )


def _profile_message_compose_html() -> str:
    return """
    <!doctype html>
    <html><body>
      <main>
        <h1>Messaging</h1>
        <section aria-label="Conversation List">
          <h3>Unrelated Person</h3>
        </section>
        <div class="scaffold-layout__detail">
          <div class="msg-convo-wrapper msg-compose-container">
            <h2>New message</h2>
            <div class="display-flex flex-column flex-grow-1">
              <section aria-label="Message recipients">
                <label for="recipient-input">Enter message recipients</label>
                <input id="recipient-input" role="combobox"
                       aria-label="Enter message recipients">
                <button aria-label="Remove Jane Doe">Jane Doe</button>
              </section>
              <ol id="compose-messages">
                <li class="msg-s-event-listitem">
                  <a href="/in/opaque-jane">Jane Doe</a>
                  <span class="msg-s-message-group__name">Jane Doe</span>
                  <p class="msg-s-event-listitem__body">Hello!</p>
                </li>
              </ol>
              <form class="msg-form">
                <div id="compose-composer" contenteditable="true" role="textbox"
                     aria-label="Write a message…" maxlength="8000"></div>
                <button id="compose-send" type="button" aria-label="Send">Send</button>
              </form>
            </div>
          </div>
        </div>
      </main>
      <script>
        document.querySelector("#compose-send").addEventListener("click", () => {
          const composer = document.querySelector("#compose-composer");
          const item = document.createElement("li");
          item.className = "msg-s-event-listitem";
          item.innerHTML =
            '<span class="msg-s-message-group__name">Current Member</span>' +
            '<p class="msg-s-event-listitem__body"></p>';
          item.querySelector("p").textContent = composer.innerText;
          document.querySelector("#compose-messages").appendChild(item);
          composer.innerText = "";
        });
      </script>
    </body></html>
    """


@pytest.mark.timeout(20)
async def test_inbox_and_conversation_fixtures_extract_both_message_directions() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content(
                (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
            )
            summaries = await ConversationSearchPage.extract_visible_conversations(page)
            await page.locator("#thread").evaluate("element => element.classList.remove('hidden')")
            conversation_root = page.get_by_role(
                "region",
                name="Conversation with Jane Doe",
            )
            observation = await ConversationPage(
                cast(BrowserManager, object()),
                max_history_rounds=1,
            )._extract(  # pyright: ignore[reportPrivateUsage]
                page,
                conversation_root,
                conversation_ref=None,
                profile_slug="jane-doe",
                participant_name="Jane Doe",
                is_group=False,
                max_messages=50,
            )
            source = source_from_conversation(observation)
        finally:
            await browser.close()

    assert [item.participant_name for item in summaries] == ["Jane Doe", "Alex Lee"]
    assert summaries[0].unread is True
    assert summaries[0].starred is True
    assert summaries[0].labels == ("Jobs",)
    assert summaries[1].muted is True
    assert summaries[0].last_message_text == "Can we discuss the role?"
    assert [message.direction for message in observation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
        MessageDirection.INCOMING,
    ]
    assert observation.messages[1].text == "Absolutely."
    assert observation.messages[1].edited is True
    assert observation.messages[1].reply_to_sender_name == "Jane Doe"
    assert observation.messages[0].reaction_summaries == ("1 like reaction",)
    assert observation.messages[2].attachments[0].name == "brief.pdf"
    assert source.captured_at == observation.captured_at
    assert str(source.source_url).endswith("/in/jane-doe/")


@pytest.mark.timeout(20)
async def test_current_thread_sender_names_resolve_outgoing_grouped_messages() -> None:
    html = """
    <!doctype html>
    <html><body><main>
      <section aria-label="Conversation with Jane Doe">
        <h2>Jane Doe</h2>
        <ol>
          <li class="msg-s-event-listitem">
            <span class="msg-s-message-group__name">Jane Doe</span>
            <p class="msg-s-event-listitem__body">Incoming.</p>
          </li>
          <li class="msg-s-event-listitem">
            <span class="msg-s-message-group__name">Current Member</span>
            <p class="msg-s-event-listitem__body">Outgoing.</p>
          </li>
          <li class="msg-s-event-listitem">
            <p class="msg-s-event-listitem__body">Outgoing continuation.</p>
          </li>
        </ol>
      </section>
    </main></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content(html)
            observation = await ConversationPage(
                cast(BrowserManager, object()),
                max_history_rounds=1,
            )._extract(  # pyright: ignore[reportPrivateUsage]
                page,
                page.get_by_role("region", name="Conversation with Jane Doe"),
                conversation_ref=None,
                profile_slug="jane-doe",
                participant_name="Jane Doe",
                is_group=False,
                max_messages=10,
            )
        finally:
            await browser.close()

    assert [message.direction for message in observation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
        MessageDirection.OUTGOING,
    ]


@pytest.mark.timeout(20)
async def test_conversation_history_collects_virtualized_older_messages() -> None:
    html = (MESSAGING_FIXTURES / "history-virtualized.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content(html)
            observation = await ConversationPage(
                cast(BrowserManager, object()),
                max_history_rounds=8,
            )._extract(  # pyright: ignore[reportPrivateUsage]
                page,
                page.get_by_role("region", name="Conversation with Jane Doe"),
                conversation_ref=None,
                profile_slug="jane-doe",
                participant_name="Jane Doe",
                is_group=False,
                max_messages=10,
            )
        finally:
            await browser.close()

    assert [message.text for message in observation.messages] == [
        "Oldest message.",
        "Older virtualized message.",
        "Current window message.",
        "Newest message.",
    ]
    assert observation.coverage.messages_observed == 4
    assert observation.coverage.rounds_visited >= 2
    assert observation.coverage.stop_reason.value == "visible_page_complete"
    assert observation.coverage.history_complete is True
    assert observation.coverage.truncated is False


@pytest.mark.timeout(20)
async def test_inbox_collection_retains_search_contract_and_visible_source() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = MessagingFixtureBrowser(page, html)
        adapter = ConversationSearchPage(
            cast(BrowserManager, fixture_browser),
            max_scroll_rounds=2,
        )
        try:
            conversations, coverage, captured_text, source_url = await adapter.collect(
                ConversationSearchInput(
                    context_id="context-1",
                    request_id="inbox-1",
                    query="Jane",
                    page_size=1,
                )
            )
        finally:
            await browser.close()

    assert len(conversations) == 1
    assert coverage.query == "Jane"
    assert coverage.stop_reason.value == "result_limit"
    assert "Can we discuss the role?" in captured_text
    assert source_url == "https://www.linkedin.com/messaging/"


@pytest.mark.timeout(20)
async def test_inbox_collection_applies_visible_unread_filter_and_server_check() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationSearchPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            max_scroll_rounds=2,
        )
        try:
            conversations, coverage, captured_text, _ = await adapter.collect(
                ConversationSearchInput(
                    context_id="messaging-context",
                    request_id="unread-inbox",
                    query="Jane",
                    filter=ConversationFilter.UNREAD,
                    page_size=5,
                )
            )
        finally:
            await browser.close()

    assert [conversation.participant_name for conversation in conversations] == [
        "Jane Doe",
        "Alex Lee",
    ]
    assert coverage.filter is ConversationFilter.UNREAD
    assert coverage.stop_reason.value == "safety_bound"
    assert "Alex Lee" in captured_text


@pytest.mark.timeout(20)
async def test_inbox_collection_retries_idle_wheel_delivery_before_terminal() -> None:
    html = (MESSAGING_FIXTURES / "search-virtualized.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationSearchPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            max_scroll_rounds=5,
        )
        try:
            conversations, coverage, captured_text, _ = await adapter.collect(
                ConversationSearchInput(
                    context_id="messaging-context",
                    request_id="delayed-inbox-tail",
                    query="message",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert [conversation.participant_name for conversation in conversations] == [
        "Jane Doe",
        "Taylor Ray",
    ]
    assert 2 <= coverage.rounds_visited <= 4
    assert coverage.stop_reason.value == "visible_page_complete"
    assert "Delayed tail message." in captured_text


@pytest.mark.timeout(30)
async def test_inbox_collection_applies_all_desktop_categories_and_filters() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for category in ConversationCategory:
                page = await browser.new_page()
                try:
                    adapter = ConversationSearchPage(
                        cast(BrowserManager, MessagingFixtureBrowser(page, html)),
                        max_scroll_rounds=1,
                    )
                    conversations, coverage, _, _ = await adapter.collect(
                        ConversationSearchInput(
                            context_id="messaging-context",
                            request_id=f"category-{category.value}",
                            category=category,
                            page_size=1,
                        )
                    )
                finally:
                    await page.close()
                assert [item.participant_name for item in conversations] == ["Jane Doe"]
                assert coverage.category is category
                assert coverage.filter is None
            for conversation_filter in ConversationFilter:
                page = await browser.new_page()
                try:
                    adapter = ConversationSearchPage(
                        cast(BrowserManager, MessagingFixtureBrowser(page, html)),
                        max_scroll_rounds=1,
                    )
                    conversations, coverage, _, _ = await adapter.collect(
                        ConversationSearchInput(
                            context_id="messaging-context",
                            request_id=f"filter-{conversation_filter.value}",
                            filter=conversation_filter,
                            page_size=1,
                        )
                    )
                finally:
                    await page.close()
                assert [item.participant_name for item in conversations] == ["Jane Doe"]
                assert coverage.category is ConversationCategory.FOCUSED
                assert coverage.filter is conversation_filter
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_current_linkless_inbox_cards_are_readable_by_visible_reference() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = cast(
            BrowserManager,
            MessagingFixtureBrowser(page, html),
        )
        search = ConversationSearchPage(
            fixture_browser,
            max_scroll_rounds=1,
        )
        adapter = ConversationPage(
            fixture_browser,
            conversation_search=search,
            max_history_rounds=1,
        )
        try:
            summaries, _, _, _ = await search.collect(
                ConversationSearchInput(
                    context_id="messaging-context",
                    request_id="current-linkless-search",
                    query="Jane",
                    page_size=1,
                )
            )
            reference = summaries[0].conversation_ref
            observation = await adapter.read(
                ConversationGetInput(
                    context_id="messaging-context",
                    request_id="current-linkless-conversation",
                    conversation_ref=reference,
                )
            )
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="current-linkless-message",
                    conversation_ref=reference,
                    message="Draft only.",
                )
            )
        finally:
            await browser.close()

    assert [item.conversation_id for item in summaries] == [None]
    assert summaries[0].participant_name == "Jane Doe"
    assert summaries[0].unread is True
    assert observation.conversation_ref == reference
    assert observation.conversation_id == "thread-current"
    assert observation.participant_profile_slug == "jane-doe"
    assert [message.direction for message in observation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
        MessageDirection.INCOMING,
    ]
    assert capture.target.profile_slug == "jane-doe"
    assert capture.target.conversation_id == "thread-current"


@pytest.mark.timeout(20)
async def test_missing_visible_conversation_reference_fails_closed() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = cast(
            BrowserManager,
            MessagingFixtureBrowser(page, html),
        )
        adapter = ConversationPage(
            fixture_browser,
            conversation_search=ConversationSearchPage(
                fixture_browser,
                max_scroll_rounds=1,
            ),
        )
        try:
            with pytest.raises(InvalidTargetError, match="unavailable"):
                await adapter.read(
                    ConversationGetInput(
                        context_id="messaging-context",
                        request_id="missing-conversation-ref",
                        conversation_ref="conversation:" + "f" * 24,
                    )
                )
        finally:
            await browser.close()


@pytest.mark.asyncio
async def test_malformed_conversation_cards_are_ignored_without_identity_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def malformed_cards(_: Page) -> list[dict[str, object]]:
        return [
            {"visible_text": ""},
            {
                "visible_text": "Fallback Person\nA visible snippet",
                "conversation_href": 42,
                "profile_href": 42,
                "profile_text": None,
                "snippet": None,
                "time": None,
                "class_name": "msg-conversation-listitem group unread",
            },
            {
                "visible_text": "Messaging\nSearch messages",
                "profile_text": "",
                "class_name": "msg-conversation-listitem",
            },
        ]

    monkeypatch.setattr(messaging_pages, "_raw_conversation_cards", malformed_cards)

    conversations = await ConversationSearchPage.extract_visible_conversations(cast(Page, object()))

    assert len(conversations) == 1
    assert conversations[0].participant_name == "Fallback Person"
    assert conversations[0].last_message_text == "A visible snippet"
    assert conversations[0].conversation_id is None
    assert conversations[0].is_group is True
    assert conversations[0].unread is True


@pytest.mark.timeout(20)
async def test_conversation_read_is_direct_by_visible_conversation_id() -> None:
    html = (FIXTURES / "messaging/latest/action.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
        try:
            observation = await adapter.read(
                ConversationGetInput(
                    context_id="context-1",
                    request_id="conversation-1",
                    conversation_id="thread-123",
                )
            )
        finally:
            await browser.close()

    assert observation.conversation_id == "thread-123"
    assert observation.participant_profile_slug == "jane-doe"
    assert observation.messages[0].text == "Hello!"


@pytest.mark.timeout(20)
async def test_message_action_verifies_a_new_exact_outgoing_bubble() -> None:
    html = (FIXTURES / "messaging/latest/action.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="context-1",
                    request_id="action-message-1",
                    conversation_id="thread-123",
                    message="Thanks for reaching out.",
                )
            )
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=ActionTarget(
                        profile_slug=capture.target.profile_slug,
                        profile_url=capture.target.profile_url,
                        display_name=capture.target.display_name,
                        conversation_id="thread-123",
                    ),
                    payload=MessageSendPayload(message="Thanks for reaching out."),
                )
            )
        finally:
            await browser.close()

    assert capture.current_state == "message_composer_available"
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"
    assert "Thanks for reaching out." in result.captured_text


@pytest.mark.timeout(30)
async def test_message_reply_is_bound_to_the_exact_history_message_and_postcondition() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            max_history_rounds=1,
        )
        try:
            observation = await adapter.read(
                ConversationGetInput(
                    context_id="messaging-context",
                    request_id="reply-history",
                    conversation_id="thread-123",
                )
            )
            replied_to = observation.messages[0]
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="reply-action",
                    conversation_id="thread-123",
                    message="Yes, let us discuss it.",
                    reply_to_message_ref=replied_to.message_ref,
                )
            )
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=capture.target,
                    payload=MessageSendPayload(
                        message="Yes, let us discuss it.",
                        reply_to_message_ref=replied_to.message_ref,
                    ),
                )
            )
        finally:
            await browser.close()

    assert replied_to.text == "Can we discuss the role?"
    assert capture.current_state == "message_reply_composer_available"
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"
    assert "Can we discuss the role?" in result.captured_text
    assert "Yes, let us discuss it." in result.captured_text


@pytest.mark.timeout(30)
async def test_message_reply_never_claims_success_for_a_plain_outgoing_bubble() -> None:
    html = (
        (MESSAGING_FIXTURES / "current.html")
        .read_text(encoding="utf-8")
        .replace(
            'appendReplyQuote(item.querySelector(".msg-s-event-listitem__message-bubble"));',
            "",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            max_history_rounds=1,
        )
        try:
            observation = await adapter.read(
                ConversationGetInput(
                    context_id="messaging-context",
                    request_id="plain-reply-history",
                    conversation_id="thread-123",
                )
            )
            replied_to = observation.messages[0]
            request = MessageSendInput(
                context_id="messaging-context",
                request_id="plain-reply-action",
                conversation_id="thread-123",
                message="This must remain a reply.",
                reply_to_message_ref=replied_to.message_ref,
            )
            capture = await adapter.inspect_message(request)
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=capture.target,
                    payload=MessageSendPayload(
                        message=request.message,
                        reply_to_message_ref=request.reply_to_message_ref,
                    ),
                )
            )
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "message_outcome_unknown"


@pytest.mark.timeout(20)
async def test_message_reply_fails_closed_for_a_visible_nonreplyable_message() -> None:
    html = (
        (MESSAGING_FIXTURES / "current.html")
        .read_text(encoding="utf-8")
        .replace(
            (
                '<button class="msg-s-event-listitem__hover-action-button" '
                'aria-label="Reply to this message">Reply</button>'
            ),
            "",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            max_history_rounds=1,
        )
        try:
            observation = await adapter.read(
                ConversationGetInput(
                    context_id="messaging-context",
                    request_id="nonreplyable-history",
                    conversation_id="thread-123",
                )
            )
            with pytest.raises(InvalidTargetError, match="no unique Reply control"):
                await adapter.inspect_message(
                    MessageSendInput(
                        context_id="messaging-context",
                        request_id="nonreplyable-action",
                        conversation_id="thread-123",
                        message="This reply is unavailable.",
                        reply_to_message_ref=observation.messages[0].message_ref,
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_message_action_accepts_exact_thread_when_profile_link_is_absent() -> None:
    html = (
        (FIXTURES / "messaging/latest/action.html")
        .read_text(encoding="utf-8")
        .replace(
            '<a href="/in/jane-doe/">Jane Doe</a>',
            "",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            result = await ConversationPage(
                cast(BrowserManager, MessagingFixtureBrowser(page, html))
            ).perform_message(_message_command())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"


@pytest.mark.timeout(60)
async def test_message_action_revalidates_exact_profile_after_stale_compose_overlay() -> None:
    thread_html = (
        (FIXTURES / "messaging/latest/action.html")
        .read_text(encoding="utf-8")
        .replace(
            '<a href="/in/jane-doe/">Jane Doe</a>',
            "",
        )
        .replace(
            "</body>",
            """
            <dialog open aria-label="New message">
              <h2>New message</h2>
              <div contenteditable="true" role="textbox"
                   aria-label="Write a message"></div>
            </dialog>
            </body>
            """,
        )
    )
    profile_html = _profile_message_html()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            result = await ConversationPage(
                cast(
                    BrowserManager,
                    RoutedMessagingFixtureBrowser(
                        page,
                        {
                            "/messaging/thread/": thread_html,
                            "/in/jane-doe/": profile_html,
                        },
                    ),
                )
            ).perform_message(_message_command())
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"


@pytest.mark.timeout(30)
async def test_profile_message_does_not_fallback_when_exact_overlay_disappears() -> None:
    html = _profile_message_html().replace(
        'composer.innerText = "";',
        'composer.innerText = "";\n          profileOverlay.hidden = true;',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="context-profile-overlay",
                    request_id="action-profile-overlay",
                    profile_slug="jane-doe",
                    message="One bounded send.",
                )
            )
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=capture.target,
                    payload=MessageSendPayload(message="One bounded send."),
                )
            )
        finally:
            await browser.close()

    assert capture.target.conversation_id is None
    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "message_outcome_unknown"


@pytest.mark.timeout(30)
async def test_message_read_and_direct_file_send_cover_visible_attachments(
    tmp_path: Path,
) -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    asset = tmp_path / "candidate-brief.pdf"
    asset.write_bytes(b"%PDF-1.4 fixture")
    request = MessageSendInput(
        context_id="messaging-context",
        request_id="attachment-action",
        conversation_id="thread-123",
        message="Here is the brief.",
        attachments=(MessageFileInput(asset_ref=asset.name),),
    )
    asset_store = LocalAssetStore(tmp_path)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            asset_store=asset_store,
            max_history_rounds=1,
        )
        try:
            await page.set_content(html)
            await page.locator("#thread").evaluate("element => element.classList.remove('hidden')")
            observation = await adapter._extract(  # pyright: ignore[reportPrivateUsage]
                page,
                page.get_by_role("region", name="Conversation with Jane Doe"),
                conversation_ref=None,
                profile_slug="jane-doe",
                participant_name="Jane Doe",
                is_group=False,
                max_messages=50,
            )
            source_from_conversation(observation)
            capture = await adapter.inspect_message(request)
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=capture.target,
                    payload=MessageSendPayload(
                        message=request.message,
                        attachment_refs=(asset.name,),
                    ),
                )
            )
        finally:
            await browser.close()

    attachment_message = next(message for message in observation.messages if message.attachments)
    assert attachment_message.attachments[0].kind is MessageAttachmentKind.DOCUMENT
    assert attachment_message.attachments[0].name == "brief.pdf"
    assert observation.coverage.attachments_returned == 1
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.final_state == "message_sent"
    assert "candidate-brief.pdf" in result.captured_text


@pytest.mark.timeout(30)
async def test_image_send_verifies_with_duplicate_dom_wrappers_and_generic_preview(
    tmp_path: Path,
) -> None:
    html = (MESSAGING_FIXTURES / "sent-image-duplicate-dom.html").read_text(encoding="utf-8")
    asset = tmp_path / "candidate-photo.png"
    asset.write_bytes(b"PNG fixture")
    request = MessageSendInput(
        context_id="messaging-context",
        request_id="image-action",
        conversation_id="thread-123",
        message="Here is the image.",
        attachments=(MessageFileInput(asset_ref=asset.name),),
    )
    asset_store = LocalAssetStore(tmp_path)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(BrowserManager, MessagingFixtureBrowser(page, html)),
            asset_store=asset_store,
        )
        try:
            capture = await adapter.inspect_message(request)
            result = await adapter.perform_message(
                ActionCommand(
                    action_type=ActionType.MESSAGE_SEND,
                    target=capture.target,
                    payload=MessageSendPayload(
                        message=request.message,
                        attachment_refs=(asset.name,),
                    ),
                )
            )
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"
    assert "Here is the image." in result.captured_text


@pytest.mark.timeout(30)
async def test_message_gif_is_verified_as_one_immediate_send() -> None:
    html = (MESSAGING_FIXTURES / "current.html").read_text(encoding="utf-8")
    request = MessageSendInput(
        context_id="messaging-context",
        request_id="gif-action",
        conversation_id="thread-123",
        gif=MessageGifInput(
            search_query="celebration",
            result_title="Celebration Dance",
        ),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
            capture = await adapter.inspect_message(request)
            command = ActionCommand(
                action_type=ActionType.MESSAGE_SEND,
                target=capture.target,
                payload=MessageSendPayload(gif=request.gif),
            )
            result = await adapter.perform_message(command)
            uncertain = await ConversationPage(
                cast(BrowserManager, FailingGifClickBrowser(page, html))
            ).perform_message(command)
        finally:
            await browser.close()

    assert capture.current_state == "message_gif_ready"
    assert result.outcome is ActionOutcome.VERIFIED
    assert "Celebration Dance" in result.captured_text
    assert uncertain.outcome is ActionOutcome.UNCERTAIN
    assert uncertain.performed is None


@pytest.mark.asyncio
async def test_every_document_image_and_video_message_format_is_resolved_directly(
    tmp_path: Path,
) -> None:
    extensions = (
        ".ai",
        ".bmp",
        ".doc",
        ".docx",
        ".eml",
        ".gif",
        ".heic",
        ".heif",
        ".jpeg",
        ".jpg",
        ".mov",
        ".mp4",
        ".pdf",
        ".png",
        ".pps",
        ".ppsx",
        ".psd",
        ".ppt",
        ".pptx",
        ".tif",
        ".tiff",
        ".txt",
        ".webp",
        ".xls",
        ".xlsx",
    )
    for index, extension in enumerate(extensions):
        path = tmp_path / f"asset-{index}{extension}"
        path.write_bytes(b"fixture")
        assets = await LocalAssetStore(tmp_path).resolve_message((path.name,))
        assert assets[path.name] == path


@pytest.mark.asyncio
async def test_message_attachment_resolution_uses_current_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "brief.pdf"
    path.write_bytes(b"confirmed")
    asset_store = LocalAssetStore(tmp_path)
    assert (await asset_store.resolve_message((path.name,)))[path.name] == path
    path.write_bytes(b"changed")
    assert (await asset_store.resolve_message((path.name,)))[path.name] == path


def test_message_content_modes_are_exact_and_mutually_safe() -> None:
    with pytest.raises(ValidationError, match="requires text"):
        MessageSendInput(
            context_id="messaging-context",
            request_id="empty-message",
            conversation_id="thread-123",
        )
    with pytest.raises(ValidationError, match="immediate-send"):
        MessageSendInput(
            context_id="messaging-context",
            request_id="mixed-gif",
            conversation_id="thread-123",
            message="Two effects",
            gif=MessageGifInput(
                search_query="robot",
                result_title="Dancing robot GIF",
            ),
        )


@pytest.mark.asyncio
async def test_message_attachments_reject_combined_size_over_20_mb(tmp_path: Path) -> None:
    refs = ("asset-0.pdf", "asset-1.pdf")
    for ref in refs:
        with (tmp_path / ref).open("wb") as stream:
            stream.truncate(11 * 1024 * 1024)
    with pytest.raises(InvalidTargetError, match="exceed 20 MB"):
        await LocalAssetStore(tmp_path).resolve_message(refs)


@pytest.mark.timeout(20)
async def test_message_inspection_rejects_groups_missing_identity_and_inmail() -> None:
    base = (FIXTURES / "messaging/latest/action.html").read_text(encoding="utf-8")
    group_html = base.replace(
        '<a href="/in/jane-doe/">Jane Doe</a>',
        '<a href="/in/jane-doe/">Jane Doe</a><a href="/in/alex-lee/">Alex Lee</a>',
    )
    missing_identity_html = base.replace('<a href="/in/jane-doe/">Jane Doe</a>', "")
    inmail_html = base.replace(
        "<h2>Jane Doe</h2>",
        '<h2>Jane Doe</h2><p>InMail</p><input aria-label="Subject" />',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            for html, message in (
                (group_html, "Group conversations"),
                (missing_identity_html, "unambiguous visible profile"),
                (inmail_html, "Paid InMail"),
            ):
                adapter = ConversationPage(
                    cast(BrowserManager, MessagingFixtureBrowser(page, html))
                )
                with pytest.raises(InvalidTargetError, match=message):
                    await adapter.inspect_message(
                        MessageSendInput(
                            context_id="messaging-context",
                            request_id=f"reject-{uuid.uuid4().hex}",
                            conversation_id="thread-123",
                            message="Hello",
                        )
                    )
        finally:
            await browser.close()


@pytest.mark.timeout(60)
async def test_profile_target_uses_exact_visible_message_button_and_same_overlay() -> None:
    html = _profile_message_html()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="profile-message-action",
                    profile_slug="jane-doe",
                    message="Hello from the profile.",
                )
            )
            result = await adapter.perform_message(
                _message_command(
                    message="Hello from the profile.",
                    conversation_id=None,
                )
            )
        finally:
            await browser.close()

    assert capture.target.profile_slug == "jane-doe"
    assert capture.target.conversation_id is None
    assert str(capture.source_url) == "https://www.linkedin.com/in/jane-doe/"
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"
    assert str(result.source_url) == "https://www.linkedin.com/in/jane-doe/"
    assert "Hello from the profile." in result.captured_text


@pytest.mark.timeout(60)
async def test_profile_target_accepts_same_window_exact_thread_after_message_click() -> None:
    html = _profile_message_thread_html()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(cast(BrowserManager, MessagingFixtureBrowser(page, html)))
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="profile-message-thread-action",
                    profile_slug="jane-doe",
                    message="Hello from the profile thread.",
                )
            )
            result = await adapter.perform_message(
                _message_command(
                    message="Hello from the profile thread.",
                    conversation_id=None,
                )
            )
        finally:
            await browser.close()

    assert capture.target.profile_slug == "jane-doe"
    assert capture.target.conversation_id == "thread-from-profile"
    assert capture.current_state == "message_composer_available"
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"


@pytest.mark.timeout(60)
async def test_profile_target_follows_exact_message_href_in_current_page() -> None:
    profile_html = _profile_message_compose_profile_html()
    thread_html = _profile_message_compose_html()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = ConversationPage(
            cast(
                BrowserManager,
                PopupMessagingFixtureBrowser(page, profile_html, thread_html),
            )
        )
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="profile-message-popup-action",
                    profile_slug="jane-doe",
                    message="Hello from the profile popup.",
                )
            )
            result = await adapter.perform_message(
                _message_command(
                    message="Hello from the profile popup.",
                    conversation_id=None,
                )
            )
            open_pages = len(page.context.pages)
        finally:
            await browser.close()

    assert capture.target.profile_slug == "jane-doe"
    assert capture.target.conversation_id is None
    assert capture.current_state == "message_composer_available"
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "message_sent"
    assert open_pages == 1


@pytest.mark.timeout(20)
async def test_profile_compose_rejects_multiple_visible_recipient_pills() -> None:
    html = _profile_message_compose_html().replace(
        '<button aria-label="Remove Jane Doe">Jane Doe</button>',
        (
            '<button aria-label="Remove Jane Doe">Jane Doe</button>'
            '<button aria-label="Remove Alex Lee">Alex Lee</button>'
        ),
    )
    url = (
        "https://www.linkedin.com/messaging/compose/?"
        "profileUrn=urn%3Ali%3Afsd_profile%3Aopaque-jane&"
        "recipient=opaque-jane"
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:

            async def fulfill(route: Route) -> None:
                await route.fulfill(status=200, content_type="text/html", body=html)

            await page.route(url, fulfill, times=1)
            await page.goto(url)
            overlays = await ConversationPage._profile_message_overlays(  # pyright: ignore[reportPrivateUsage]
                page,
                profile_name="Jane Doe",
            )
        finally:
            await browser.close()

    assert overlays == []


@pytest.mark.timeout(30)
async def test_profile_target_leaves_named_blank_page_unchanged() -> None:
    profile_html = _profile_message_popup_html().replace(
        'target="_blank"',
        'target="messaging-window"',
    )
    thread_html = (FIXTURES / "messaging/latest/action.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        named_page = await browser.new_page()
        await named_page.evaluate("window.name = 'messaging-window'")
        adapter = ConversationPage(
            cast(
                BrowserManager,
                PopupMessagingFixtureBrowser(page, profile_html, thread_html),
            )
        )
        try:
            capture = await adapter.inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="profile-message-named-page-action",
                    profile_slug="jane-doe",
                    message="Draft only.",
                )
            )
            named_page_url = named_page.url
        finally:
            await browser.close()

    assert capture.target.profile_slug == "jane-doe"
    assert capture.current_state == "message_composer_available"
    assert named_page_url == "about:blank"


@pytest.mark.timeout(20)
async def test_profile_target_accepts_a_visible_message_link_action() -> None:
    html = _profile_message_html().replace(
        '<button id="profile-message" aria-label="Message Jane Doe">Message</button>',
        (
            '<a id="profile-message" href="#profile-message-overlay" '
            'aria-label="Message Jane Doe">Message</a>'
        ),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            capture = await ConversationPage(
                cast(BrowserManager, MessagingFixtureBrowser(page, html))
            ).inspect_message(
                MessageSendInput(
                    context_id="messaging-context",
                    request_id="profile-message-link",
                    profile_slug="jane-doe",
                    message="Draft only.",
                )
            )
        finally:
            await browser.close()

    assert capture.target.display_name == "Jane Doe"
    assert capture.current_state == "message_composer_available"


@pytest.mark.timeout(20)
async def test_profile_page_fallback_selects_visual_nearest_message_action() -> None:
    html = """
    <html><body><main style="position: relative; height: 900px">
      <button id="far-message" aria-label="Message Jane Doe"
              style="position: absolute; left: 600px; top: 700px">Message</button>
      <section id="profile-introduction"
               style="position: absolute; left: 100px; top: 100px">
        <h1>Jane Doe</h1><p>1st degree connection</p>
      </section>
      <button id="near-message" aria-label="Message Jane Doe"
              style="position: absolute; left: 300px; top: 120px">Message</button>
    </main></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 900, "height": 900})
        selected_id: str | None = None
        try:
            await page.set_content(html)
            candidates = await ConversationPage._visible_profile_message_controls(  # pyright: ignore[reportPrivateUsage]
                page.locator("main"),
                profile_name="Jane Doe",
            )
            selected = await ConversationPage._nearest_profile_message_control(  # pyright: ignore[reportPrivateUsage]
                candidates,
                anchor=page.locator("#profile-introduction"),
            )
            assert selected is not None
            selected_id = await selected.get_attribute("id")
        finally:
            await browser.close()

    assert selected_id == "near-message"


@pytest.mark.timeout(30)
async def test_profile_message_fails_closed_for_ambiguous_button_or_existing_draft() -> None:
    html = _profile_message_html()
    ambiguous_html = html.replace(
        '<button id="profile-message" aria-label="Message Jane Doe">Message</button>',
        """
        <button id="profile-message" aria-label="Message Jane Doe">Message</button>
        <button aria-label="Message Jane Doe">Message</button>
        """,
    )
    existing_draft_html = html.replace(
        'aria-label="Write a message" maxlength="8000"></div>',
        'aria-label="Write a message" maxlength="8000">Existing draft</div>',
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for html, error in (
                (ambiguous_html, "multiple visible standard Message actions"),
                (existing_draft_html, "already contains unsent text"),
            ):
                page = await browser.new_page()
                try:
                    adapter = ConversationPage(
                        cast(BrowserManager, MessagingFixtureBrowser(page, html))
                    )
                    with pytest.raises(InvalidTargetError, match=error):
                        await adapter.inspect_message(
                            MessageSendInput(
                                context_id="messaging-context",
                                request_id=f"compose-reject-{uuid.uuid4().hex}",
                                profile_slug="jane-doe",
                                message="Hello",
                            )
                        )
                finally:
                    await page.close()
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_profile_target_rejects_nonconnection() -> None:
    nonconnection_html = """
    <html><body><main>
      <h1>Jane Doe</h1><p>2nd degree connection</p>
      <button aria-label="Message Jane Doe">Message</button>
    </main></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            adapter = ConversationPage(
                cast(BrowserManager, MessagingFixtureBrowser(page, nonconnection_html))
            )
            with pytest.raises(InvalidTargetError, match="first-degree"):
                await adapter.inspect_message(
                    MessageSendInput(
                        context_id="messaging-context",
                        request_id=f"profile-reject-{uuid.uuid4().hex}",
                        profile_slug="jane-doe",
                        message="Hello",
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(40)
async def test_profile_message_rejects_missing_or_conflicting_identity_evidence() -> None:
    missing_heading = "<html><body><main><p>1st degree connection</p></main></body></html>"
    missing_button = (
        _profile_message_html()
        .replace(
            '<button id="profile-message" aria-label="Message Jane Doe">Message</button>',
            "",
        )
        .replace(
            '<button aria-label="Message Jane Doe">Message</button>',
            "",
        )
    )
    conflicting_overlay = (
        _profile_message_html()
        .replace(
            'aria-label="Conversation with Jane Doe"',
            'aria-label="Conversation with Jane Roe"',
        )
        .replace(
            '<h2><a href="/in/jane-doe/">Jane Doe</a></h2>',
            '<h2><a href="/in/jane-roe/">Jane Roe</a></h2>',
        )
        .replace(
            '<span class="msg-s-message-group__name">Jane Doe</span>',
            '<span class="msg-s-message-group__name">Jane Roe</span>',
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            missing_adapter = ConversationPage(
                cast(BrowserManager, MessagingFixtureBrowser(page, missing_heading))
            )
            with pytest.raises(ParserDriftError, match="member heading"):
                await missing_adapter.inspect_message(
                    MessageSendInput(
                        context_id="messaging-context",
                        request_id="missing-profile-heading",
                        profile_slug="jane-doe",
                        message="Hello",
                    )
                )

            for html, exception, error in (
                (
                    missing_button,
                    InvalidTargetError,
                    "no visible standard Message action",
                ),
                (
                    conflicting_overlay,
                    ParserDriftError,
                    "did not open one exact-recipient",
                ),
            ):
                adapter = ConversationPage(
                    cast(BrowserManager, MessagingFixtureBrowser(page, html))
                )
                with pytest.raises(exception, match=error):
                    await adapter.inspect_message(
                        MessageSendInput(
                            context_id="messaging-context",
                            request_id=f"identity-reject-{uuid.uuid4().hex}",
                            profile_slug="jane-doe",
                            message="Hello",
                        )
                    )
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_message_action_fails_closed_for_changed_target_limits_and_controls() -> None:
    base = (FIXTURES / "messaging/latest/action.html").read_text(encoding="utf-8")
    cases = (
        (
            base,
            _message_command(display_name="Jane Roe"),
            "target_identity_changed",
            ActionOutcome.FAILED,
            "display_name_changed",
        ),
        (
            base.replace("/in/jane-doe/", "/in/jane-roe/"),
            _message_command(),
            "target_identity_changed",
            ActionOutcome.FAILED,
            "profile_slug_changed",
        ),
        (
            base.replace(
                "<body>",
                '<body><script>history.replaceState({}, "", '
                '"/messaging/thread/thread-changed/");</script>',
            ),
            _message_command(),
            "target_identity_changed",
            ActionOutcome.FAILED,
            "conversation_id_changed",
        ),
        (
            base.replace('maxlength="8000"', 'maxlength="1"'),
            _message_command(message="Too long"),
            "message_too_long",
            ActionOutcome.FAILED,
            None,
        ),
        (
            base.replace('aria-label="Send"', 'aria-label="Archive"'),
            _message_command(),
            "message_send_unavailable",
            ActionOutcome.FAILED,
            None,
        ),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            for html, command, expected_state, expected_outcome, expected_detail in cases:
                result = await ConversationPage(
                    cast(BrowserManager, MessagingFixtureBrowser(page, html))
                ).perform_message(command)
                assert result.final_state == expected_state
                assert result.outcome is expected_outcome
                if expected_detail is not None:
                    assert expected_detail in result.detail

            uncertain = await ConversationPage(
                cast(BrowserManager, FailingMessageClickBrowser(page, base))
            ).perform_message(_message_command())
        finally:
            await browser.close()

    assert uncertain.outcome is ActionOutcome.UNCERTAIN
    assert uncertain.performed is None
    assert uncertain.final_state == "message_outcome_unknown"


@pytest.mark.timeout(20)
async def test_composer_fallbacks_and_message_extraction_remain_bounded() -> None:
    html = """
    <html><body><main>
      <h1>Conversation</h1>
      <ol>
        <li class="msg-s-event-listitem msg-s-event-listitem--incoming">
          <p data-test-message-body>First</p>
        </li>
        <li class="msg-s-event-listitem" data-direction="outgoing">
          <span data-test-message-sender>You</span>
          <p data-test-message-body>Second</p>
        </li>
        <li class="msg-s-event-listitem system">
          <p data-test-message-body>Jane joined LinkedIn</p>
        </li>
        <li class="msg-s-event-listitem"><span>No message body</span></li>
      </ol>
      <textarea></textarea>
    </main></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content(html)
            root = page.locator("main")
            composer = await ConversationPage._composer(  # pyright: ignore[reportPrivateUsage]
                root
            )
            await composer.fill("draft")
            assert (
                await ConversationPage._composer_value(  # pyright: ignore[reportPrivateUsage]
                    composer
                )
                == "draft"
            )
            observation = await ConversationPage(
                cast(BrowserManager, object()),
                max_history_rounds=1,
            )._extract(  # pyright: ignore[reportPrivateUsage]
                page,
                root,
                conversation_ref=None,
                profile_slug=None,
                participant_name="Jane Doe",
                is_group=False,
                max_messages=2,
            )

            await page.set_content("<html><body><main>Empty conversation</main></body></html>")
            with pytest.raises(InvalidTargetError, match="composer"):
                await ConversationPage._composer(  # pyright: ignore[reportPrivateUsage]
                    page.locator("main")
                )
            await page.set_content(
                "<html><body><main><textarea></textarea><textarea></textarea></main></body></html>"
            )
            with pytest.raises(InvalidTargetError, match="unique"):
                await ConversationPage._composer(  # pyright: ignore[reportPrivateUsage]
                    page.locator("main")
                )
        finally:
            await browser.close()

    assert observation.coverage.messages_observed == 3
    assert observation.coverage.messages_returned == 2
    assert observation.coverage.truncated is True
    assert [message.direction for message in observation.messages] == [
        MessageDirection.OUTGOING,
        MessageDirection.SYSTEM,
    ]


@pytest.mark.asyncio
async def test_message_action_payload_type_is_enforced_before_browser_access() -> None:
    wrong = ActionCommand(
        action_type=ActionType.INVITATION_SEND,
        target=ActionTarget(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            display_name="Jane Doe",
        ),
        payload=InvitationSendPayload(note=None),
    )

    with pytest.raises(InvalidTargetError, match="message action payload"):
        await ConversationPage(cast(BrowserManager, object())).perform_message(wrong)


@pytest.mark.timeout(20)
async def test_missing_visible_messaging_containers_fail_closed() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content("<html><body><main></main></body></html>")
            with pytest.raises(ParserDriftError, match="no visible text"):
                await messaging_pages._visible_text(  # pyright: ignore[reportPrivateUsage]
                    page.locator("main")
                )
            with pytest.raises(ParserDriftError, match="no visible container"):
                await messaging_pages._visible_text(  # pyright: ignore[reportPrivateUsage]
                    page.locator("section")
                )
        finally:
            await browser.close()


def test_conversation_inputs_require_exactly_one_target() -> None:
    with pytest.raises(ValidationError, match="Exactly one"):
        ConversationGetInput(
            context_id="messaging-context",
            request_id="missing-target",
        )
    with pytest.raises(ValidationError, match="Exactly one"):
        MessageSendInput(
            context_id="messaging-context",
            request_id="two-targets",
            profile_slug="jane-doe",
            conversation_id="thread-123",
            message="Hello",
        )


def test_message_search_requires_one_current_search_criterion() -> None:
    with pytest.raises(ValidationError, match="requires query, category, or one visible"):
        ConversationSearchInput(
            context_id="messaging-context",
            request_id="missing-search-criterion",
        )

    request = ConversationSearchInput(
        context_id="messaging-context",
        request_id="combined-current-criteria",
        query="interview",
        category=ConversationCategory.ARCHIVED,
        filter=ConversationFilter.JOBS,
    )

    assert request.resolved_category is ConversationCategory.ARCHIVED
    assert request.filter is ConversationFilter.JOBS


def test_action_command_rejects_a_payload_from_another_action_type() -> None:
    valid = _message_command()

    with pytest.raises(ValidationError, match="does not match"):
        ActionCommand.model_validate(
            {
                **valid.model_dump(mode="json"),
                "action_type": ActionType.INVITATION_SEND.value,
            }
        )
