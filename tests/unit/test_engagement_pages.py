from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import ValidationError

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.pages import PostEngagementPage
from linkedin_mcp.browser.pages import engagement as engagement_page
from linkedin_mcp.domain.models import (
    ActionCommand,
    ActionOutcome,
    ActionType,
    CommentCreatePayload,
    CommentGifAttachment,
    CommentPhotoAttachment,
    PostCommentInput,
    PostMentionInput,
    PostReactionInput,
    ReactionSetPayload,
    ReactionState,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
ENGAGEMENT_HTML = (FIXTURES / "posts/latest/engagement.html").read_text(encoding="utf-8")
CURRENT_REACTION_HTML = (FIXTURES / "posts/latest/reaction.html").read_text(encoding="utf-8")
POST_REF = "activity:7312345678901234567"
COMMENT_REF = "comment:ugc-post:7312345678901234566:111"


def _role_article_target(html: str) -> str:
    return html.replace(
        '<article\n        id="target-post"',
        '<div\n        role="article"\n        id="target-post"',
        1,
    ).replace("</article>", "</div>", 1)


def test_visible_comment_text_match_only_ignores_expansion_affordance() -> None:
    matches = engagement_page._visible_comment_text_matches  # pyright: ignore[reportPrivateUsage]
    text = "An exact long comment."

    assert matches(text, text)
    assert matches(f"{text}\n… more", text)
    assert matches(f"{text}\n... MORE", text)
    assert not matches(f"{text} … more", text)
    assert not matches(f"{text}\n… more context", text)


def _comment_result_html(
    *,
    stable_reference: bool,
    clear_composer: bool,
    expansion_suffix: bool = False,
) -> str:
    html = ENGAGEMENT_HTML
    if not stable_reference:
        html = html.replace(
            """          comment.dataset.commentUrn =
            `urn:li:comment:(ugcPost:7312345678901234566,${commentId})`;""",
            '          comment.className = "comments-comment-entity";',
            1,
        )
    if clear_composer:
        html = html.replace(
            '          document.querySelector("#discussion").append(comment);',
            """          document.querySelector("#discussion").append(comment);
          composer.querySelector("textarea").value = "";""",
            1,
        )
    if expansion_suffix:
        html = html.replace(
            "            body.textContent = text;",
            """            body.textContent = text;
            const expansion = document.createElement("button");
            expansion.type = "button";
            expansion.textContent = "… more";
            expansion.style.display = "block";
            body.append(expansion);""",
            1,
        )
    return html


class EngagementFixtureBrowser:
    def __init__(
        self,
        page: Page,
        *,
        html: str = ENGAGEMENT_HTML,
        second_html: str | None = None,
        fail_final_click: bool = False,
    ) -> None:
        self._page = page
        self._html = html
        self._second_html = second_html
        self._fail_final_click = fail_final_click
        self.navigations = 0

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations += 1
        html = (
            self._second_html
            if self.navigations > 1 and self._second_html is not None
            else self._html
        )

        async def fulfill(route: Route) -> None:
            await route.fulfill(status=200, content_type="text/html", body=html)

        await page.route(url, fulfill, times=1)
        await page.goto(url)

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        del page
        if self._fail_final_click:
            label = (await control.inner_text()).strip().casefold()
            if label in {
                "comment",
                "reply",
                "like",
                "celebrate",
                "support",
                "love",
                "insightful",
                "funny",
            }:
                raise RuntimeError("fixture final click interrupted")
        await control.click()


async def _comment_command(
    adapter: PostEngagementPage,
    request: PostCommentInput,
) -> ActionCommand:
    capture = await adapter.inspect_comment(request)
    return ActionCommand(
        action_type=ActionType.COMMENT_CREATE,
        target=capture.target,
        payload=CommentCreatePayload(
            post_ref=request.post_ref,
            text=request.text,
            mentions=request.mentions,
            attachment=request.attachment,
        ),
    )


async def _reaction_command(
    adapter: PostEngagementPage,
    request: PostReactionInput,
) -> ActionCommand:
    capture = await adapter.inspect_reaction(request)
    assert capture.existing_reaction is not None
    return ActionCommand(
        action_type=ActionType.REACTION_SET,
        target=capture.target,
        payload=ReactionSetPayload(
            post_ref=request.post_ref,
            existing_reaction=capture.existing_reaction,
            desired_reaction=request.desired_reaction,
        ),
    )


@pytest.mark.timeout(30)
async def test_top_level_comment_preserves_text_link_emoji_mention_and_target(
    tmp_path: Path,
) -> None:
    text = "Thanks @Alex — useful! 🚀 https://example.com/guide"
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-top-level-comment",
        post_ref=POST_REF,
        text=text,
        mentions=(PostMentionInput(token="@Alex", profile_slug="alex-ray"),),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _comment_command(adapter, request)
            result = await adapter.perform_comment(command)
        finally:
            await browser.close()

    assert command.target.actor_profile_slug == "current-member"
    assert command.target.content_author_name == "Jane Doe"
    assert command.target.post_ref == POST_REF
    assert command.target.post_ref == POST_REF
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:comment:ugc-post:7312345678901234566:")
    assert text in result.captured_text


@pytest.mark.timeout(30)
async def test_comment_requires_stable_reference_despite_visible_delta_and_cleared_composer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engagement_page, "_COMMENT_VERIFICATION_ATTEMPTS", 2)
    monkeypatch.setattr(engagement_page, "_COMMENT_VERIFICATION_DELAY_MS", 1)
    text = "A visible comment without a stable reference."
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-without-stable-reference",
        post_ref=POST_REF,
        text=text,
    )
    fixture_browser: EngagementFixtureBrowser
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = EngagementFixtureBrowser(
            page,
            html=_comment_result_html(
                stable_reference=False,
                clear_composer=True,
            ),
        )
        adapter = PostEngagementPage(
            cast(BrowserManager, fixture_browser),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "comment_outcome_unknown"
    assert "stable comment reference" in result.detail
    assert text in result.captured_text
    assert fixture_browser.navigations == 2


@pytest.mark.timeout(30)
async def test_comment_verifies_stable_reference_with_visible_expansion_affordance(
    tmp_path: Path,
) -> None:
    text = "A long exact comment that LinkedIn truncates in the visible discussion."
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-truncated-stable-comment",
        post_ref=POST_REF,
        text=text,
    )
    html = _comment_result_html(
        stable_reference=True,
        clear_composer=False,
        expansion_suffix=True,
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:comment:")


@pytest.mark.timeout(30)
async def test_comment_submit_ignores_visible_comment_count_control(tmp_path: Path) -> None:
    html = ENGAGEMENT_HTML.replace(
        '<div\n          id="top-level-composer"',
        (
            '<button type="button" aria-label="Comment">6</button>\n\n'
            '        <div\n          id="top-level-composer"'
        ),
    )
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-with-count-control",
        post_ref=POST_REF,
        text="thanks",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:")


@pytest.mark.timeout(30)
async def test_comment_waits_for_async_composer_after_count_control(tmp_path: Path) -> None:
    html = ENGAGEMENT_HTML.replace(
        '<div\n          id="top-level-composer"',
        (
            '<button type="button" aria-label="Comment" '
            'onclick="setTimeout(() => '
            "document.getElementById('top-level-composer').removeAttribute('hidden'), 600)\">"
            "6</button>\n\n"
            '        <div hidden\n          id="top-level-composer"'
        ),
    )
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-with-async-composer",
        post_ref=POST_REF,
        text="thanks",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:")


@pytest.mark.timeout(30)
async def test_comment_waits_for_async_named_active_member_link(tmp_path: Path) -> None:
    html = ENGAGEMENT_HTML.replace(
        '<a href="/in/current-member/">\n          Current Member',
        '<a hidden href="/in/current-member/">\n          Current Member',
        1,
    ).replace(
        "</body>",
        (
            "<script>setTimeout(() => "
            "document.querySelector('aside a').removeAttribute('hidden'), 600);</script>"
            "</body>"
        ),
        1,
    )
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-with-async-actor",
        post_ref=POST_REF,
        text="thanks",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _comment_command(adapter, request)
            assert command.target.actor_display_name == "Current Member"
            result = await adapter.perform_comment(command)
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True


@pytest.mark.timeout(30)
async def test_comment_verifies_native_ugc_discussion_alias_for_activity_url(
    tmp_path: Path,
) -> None:
    html = ENGAGEMENT_HTML.replace(
        "urn:li:comment:(ugcPost:7312345678901234566,",
        "urn:li:comment:(ugcPost:7999999999999999998,",
    )
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-with-native-discussion-alias",
        post_ref=POST_REF,
        text="thanks",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:comment:ugc-post:7999999999999999998:")


@pytest.mark.timeout(30)
async def test_comment_accepts_single_rendered_post_alias_for_requested_activity(
    tmp_path: Path,
) -> None:
    html = (
        _role_article_target(ENGAGEMENT_HTML)
        .replace(
            'data-post-urn="urn:li:activity:7312345678901234567"',
            'data-post-urn="urn:li:share:7999999999999999997"',
        )
        .replace(
            'aria-label="Text editor for creating comment"',
            'aria-label="Text editor for creating content"',
            1,
        )
    )
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-comment-with-rendered-post-alias",
        post_ref=POST_REF,
        text="thanks",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True


@pytest.mark.timeout(30)
async def test_reaction_accepts_single_rendered_post_alias_for_requested_activity(
    tmp_path: Path,
) -> None:
    html = _role_article_target(ENGAGEMENT_HTML).replace(
        'data-post-urn="urn:li:activity:7312345678901234567"',
        'data-post-urn="urn:li:share:7999999999999999997"',
    )
    request = PostReactionInput(
        context_id="engagement-context",
        request_id="action-reaction-with-rendered-post-alias",
        post_ref=POST_REF,
        desired_reaction=ReactionState.LIKE,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_reaction(await _reaction_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True


@pytest.mark.timeout(40)
@pytest.mark.parametrize("attachment_kind", ["photo", "gif"])
async def test_comment_photo_and_gif_are_exact_and_verifiable(
    tmp_path: Path,
    attachment_kind: str,
) -> None:
    if attachment_kind == "photo":
        (tmp_path / "comment.png").write_bytes(b"fixture-comment-image")
        attachment = CommentPhotoAttachment(asset_ref="comment.png")
        expected = "Photo attachment"
    else:
        attachment = CommentGifAttachment(
            search_query="celebration",
            visible_result_label="Celebration confetti GIF",
        )
        expected = "Celebration confetti GIF"
    request = PostCommentInput(
        context_id="engagement-context",
        request_id=f"action-{attachment_kind}-comment",
        post_ref=POST_REF,
        attachment=attachment,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _comment_command(adapter, request)
            result = await adapter.perform_comment(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, CommentCreatePayload)
    assert command.payload.attachment == attachment
    assert result.outcome is ActionOutcome.VERIFIED
    assert expected in result.captured_text


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    "desired",
    [
        ReactionState.LIKE,
        ReactionState.CELEBRATE,
        ReactionState.SUPPORT,
        ReactionState.LOVE,
        ReactionState.INSIGHTFUL,
        ReactionState.FUNNY,
    ],
)
async def test_post_supports_every_visible_linkedin_reaction(
    tmp_path: Path,
    desired: ReactionState,
) -> None:
    request = PostReactionInput(
        context_id="engagement-context",
        request_id=f"action-post-{desired.value}",
        post_ref=POST_REF,
        desired_reaction=desired,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _reaction_command(adapter, request)
            result = await adapter.perform_reaction(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, ReactionSetPayload)
    assert command.payload.existing_reaction is ReactionState.NONE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == f"reaction_set:{desired.value}"


@pytest.mark.timeout(30)
async def test_current_portaled_reaction_control_is_inspected_and_verified(
    tmp_path: Path,
) -> None:
    request = PostReactionInput(
        context_id="engagement-context",
        request_id="action-current-portaled-reaction",
        post_ref=POST_REF,
        desired_reaction=ReactionState.FUNNY,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(
                BrowserManager,
                EngagementFixtureBrowser(page, html=CURRENT_REACTION_HTML),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _reaction_command(adapter, request)
            result = await adapter.perform_reaction(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, ReactionSetPayload)
    assert command.payload.existing_reaction is ReactionState.NONE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "reaction_set:funny"


@pytest.mark.timeout(30)
async def test_react_label_and_pressed_state_are_inspected_and_verified(
    tmp_path: Path,
) -> None:
    html = (
        CURRENT_REACTION_HTML.replace(
            'aria-label="Reaction button state: no reaction"',
            'aria-label="React Like" aria-pressed="false"',
            1,
        )
        .replace(
            """          control.setAttribute(
            "aria-label",
            `Reaction button state: ${reaction}`
          );""",
            """          control.setAttribute("aria-label", `React ${reaction}`);
          control.setAttribute("aria-pressed", "true");""",
            1,
        )
        .replace(
            "picker.hidden = false;",
            "setTimeout(() => { picker.hidden = false; }, 600);",
            1,
        )
    )
    request = PostReactionInput(
        context_id="engagement-context",
        request_id="action-react-label-and-pressed-state",
        post_ref=POST_REF,
        desired_reaction=ReactionState.FUNNY,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=html)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _reaction_command(adapter, request)
            result = await adapter.perform_reaction(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, ReactionSetPayload)
    assert command.payload.existing_reaction is ReactionState.NONE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == "reaction_set:funny"


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    ("desired", "performed", "final_state"),
    [
        (ReactionState.NONE, True, "reaction_removed"),
        (ReactionState.LIKE, False, "reaction_set:like"),
        (ReactionState.LOVE, True, "reaction_set:love"),
    ],
)
async def test_post_reaction_removal_noop_and_change(
    tmp_path: Path,
    desired: ReactionState,
    performed: bool,
    final_state: str,
) -> None:
    initially_liked = ENGAGEMENT_HTML.replace(
        'data-current-reaction="none"', 'data-current-reaction="like"', 1
    ).replace('aria-pressed="false"', 'aria-pressed="true"', 1)
    request = PostReactionInput(
        context_id="engagement-context",
        request_id=f"action-post-{desired.value}",
        post_ref=POST_REF,
        desired_reaction=desired,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page, html=initially_liked)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _reaction_command(adapter, request)
            result = await adapter.perform_reaction(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, ReactionSetPayload)
    assert command.payload.existing_reaction is ReactionState.LIKE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is performed
    assert result.final_state == final_state


@pytest.mark.timeout(30)
async def test_reaction_refuses_state_drift_after_inspection(tmp_path: Path) -> None:
    changed = (
        ENGAGEMENT_HTML.replace(
            'data-current-reaction="none"',
            'data-current-reaction="celebrate"',
            1,
        )
        .replace(
            'aria-label="Like"',
            'aria-label="Celebrate"',
            1,
        )
        .replace('aria-pressed="false"', 'aria-pressed="true"', 1)
    )
    request = PostReactionInput(
        context_id="engagement-context",
        request_id="action-state-drift",
        post_ref=POST_REF,
        desired_reaction=ReactionState.LOVE,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(
                BrowserManager,
                EngagementFixtureBrowser(page, second_html=changed),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_reaction(await _reaction_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "reaction_state_changed"


@pytest.mark.timeout(30)
async def test_reaction_reports_missing_preclick_control_as_not_changed(
    tmp_path: Path,
) -> None:
    missing_control = ENGAGEMENT_HTML.replace(
        "data-reaction-control",
        "data-unavailable-reaction-control",
        1,
    )
    request = PostReactionInput(
        context_id="engagement-context",
        request_id="action-missing-action-control",
        post_ref=POST_REF,
        desired_reaction=ReactionState.LOVE,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(
                BrowserManager,
                EngagementFixtureBrowser(page, second_html=missing_control),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_reaction(await _reaction_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "reaction_not_changed"


@pytest.mark.timeout(30)
async def test_comment_refuses_actor_or_content_target_drift(tmp_path: Path) -> None:
    changed = ENGAGEMENT_HTML.replace(
        "/in/current-member/",
        "/in/other-member/",
        2,
    ).replace("Current Member", "Other Member", 1)
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-target-drift",
        post_ref=POST_REF,
        text="This must not be submitted.",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(
                BrowserManager,
                EngagementFixtureBrowser(page, second_html=changed),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "engagement_target_changed"
    assert "This must not be submitted." not in result.captured_text


@pytest.mark.timeout(30)
async def test_interrupted_final_comment_click_is_uncertain(tmp_path: Path) -> None:
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-interrupted-comment",
        post_ref=POST_REF,
        text="An interrupted final action.",
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(
                BrowserManager,
                EngagementFixtureBrowser(page, fail_final_click=True),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            result = await adapter.perform_comment(await _comment_command(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "comment_outcome_unknown"


async def test_comment_upload_uses_current_attachment_file(tmp_path: Path) -> None:
    (tmp_path / "comment.png").write_bytes(b"confirmed")
    request = PostCommentInput(
        context_id="engagement-context",
        request_id="action-direct-comment-attachment",
        post_ref=POST_REF,
        attachment=CommentPhotoAttachment(asset_ref="comment.png"),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostEngagementPage(
            cast(BrowserManager, EngagementFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _comment_command(adapter, request)
            (tmp_path / "comment.png").write_bytes(b"changed")
            result = await adapter.perform_comment(command)
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED


def test_engagement_contract_rejects_empty_inputs_and_allows_native_discussion_aliases() -> None:
    with pytest.raises(ValidationError, match="requires text, a photo, or a GIF"):
        PostCommentInput(
            context_id="engagement-context",
            request_id="empty-comment",
            post_ref=POST_REF,
        )
    with pytest.raises(ValidationError, match="mentions require comment text"):
        PostCommentInput(
            context_id="engagement-context",
            request_id="mention-without-text",
            post_ref=POST_REF,
            mentions=(PostMentionInput(token="@Alex", profile_slug="alex-ray"),),
            attachment=CommentGifAttachment(
                search_query="celebration",
                visible_result_label="Celebration confetti GIF",
            ),
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PostCommentInput.model_validate(
            {
                "context_id": "engagement-context",
                "request_id": "threaded-reply-not-supported",
                "post_ref": POST_REF,
                "parent_comment_ref": COMMENT_REF,
                "text": "Threaded reply",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PostReactionInput.model_validate(
            {
                "context_id": "engagement-context",
                "request_id": "comment-reaction-not-supported",
                "post_ref": POST_REF,
                "comment_ref": COMMENT_REF,
                "desired_reaction": "like",
            }
        )
