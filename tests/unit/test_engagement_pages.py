from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import ValidationError

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.pages import PostEngagementPage
from linkedin_mcp.domain.models import (
    ActionDraft,
    ActionOutcome,
    ActionStatus,
    ActionType,
    CommentCreatePayload,
    CommentGifAttachment,
    CommentPhotoAttachment,
    PostCommentPrepareInput,
    PostMentionInput,
    PostReactionPrepareInput,
    ReactionSetPayload,
    ReactionState,
)
from linkedin_mcp.errors import InvalidTargetError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
ENGAGEMENT_HTML = (FIXTURES / "post-engagement.html").read_text()
CURRENT_REACTION_HTML = (FIXTURES / "post-reaction-current.html").read_text()
POST_REF = "activity:7312345678901234567"
COMMENT_REF = "comment:ugc-post:7312345678901234566:111"


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


async def _comment_draft(
    adapter: PostEngagementPage,
    request: PostCommentPrepareInput,
) -> ActionDraft:
    capture = await adapter.prepare_comment(request)
    assets = await adapter.prepare_comment_assets(request)
    now = datetime.now(UTC)
    return ActionDraft(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.COMMENT_CREATE,
        target=capture.target,
        payload=CommentCreatePayload(
            post_ref=request.post_ref,
            text=request.text,
            mentions=request.mentions,
            attachment=request.attachment,
            assets=assets,
        ),
        payload_hash="a" * 64,
        status=ActionStatus.EXECUTING,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


async def _reaction_draft(
    adapter: PostEngagementPage,
    request: PostReactionPrepareInput,
) -> ActionDraft:
    capture = await adapter.prepare_reaction(request)
    assert capture.existing_reaction is not None
    now = datetime.now(UTC)
    return ActionDraft(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.REACTION_SET,
        target=capture.target,
        payload=ReactionSetPayload(
            post_ref=request.post_ref,
            existing_reaction=capture.existing_reaction,
            desired_reaction=request.desired_reaction,
        ),
        payload_hash="b" * 64,
        status=ActionStatus.EXECUTING,
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.mark.timeout(30)
async def test_top_level_comment_preserves_text_link_emoji_mention_and_target(
    tmp_path: Path,
) -> None:
    text = "Thanks @Alex — useful! 🚀 https://example.com/guide"
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-top-level-comment",
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
            draft = await _comment_draft(adapter, request)
            result = await adapter.execute_comment(draft)
        finally:
            await browser.close()

    assert draft.target.actor_profile_slug == "current-member"
    assert draft.target.content_author_name == "Jane Doe"
    assert draft.target.post_ref == POST_REF
    assert draft.target.post_ref == POST_REF
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:comment:ugc-post:7312345678901234566:")
    assert text in result.captured_text


@pytest.mark.timeout(30)
async def test_comment_submit_ignores_visible_comment_count_control(tmp_path: Path) -> None:
    html = ENGAGEMENT_HTML.replace(
        '<div\n          id="top-level-composer"',
        (
            '<button type="button" aria-label="Comment">6</button>\n\n'
            '        <div\n          id="top-level-composer"'
        ),
    )
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-comment-with-count-control",
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
            result = await adapter.execute_comment(await _comment_draft(adapter, request))
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
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-comment-with-async-composer",
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
            result = await adapter.execute_comment(await _comment_draft(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:")


@pytest.mark.timeout(30)
async def test_comment_verifies_native_ugc_discussion_alias_for_activity_url(
    tmp_path: Path,
) -> None:
    html = ENGAGEMENT_HTML.replace(
        "urn:li:comment:(ugcPost:7312345678901234566,",
        "urn:li:comment:(ugcPost:7999999999999999998,",
    )
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-comment-with-native-discussion-alias",
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
            result = await adapter.execute_comment(await _comment_draft(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("comment_published:comment:ugc-post:7999999999999999998:")


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
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id=f"prepare-{attachment_kind}-comment",
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
            draft = await _comment_draft(adapter, request)
            result = await adapter.execute_comment(draft)
        finally:
            await browser.close()

    assert isinstance(draft.payload, CommentCreatePayload)
    assert len(draft.payload.assets) == (1 if attachment_kind == "photo" else 0)
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
    request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id=f"prepare-post-{desired.value}",
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
            draft = await _reaction_draft(adapter, request)
            result = await adapter.execute_reaction(draft)
        finally:
            await browser.close()

    assert isinstance(draft.payload, ReactionSetPayload)
    assert draft.payload.existing_reaction is ReactionState.NONE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state == f"reaction_set:{desired.value}"


@pytest.mark.timeout(30)
async def test_current_portaled_reaction_control_is_prepared_and_verified(
    tmp_path: Path,
) -> None:
    request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id="prepare-current-portaled-reaction",
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
            draft = await _reaction_draft(adapter, request)
            result = await adapter.execute_reaction(draft)
        finally:
            await browser.close()

    assert isinstance(draft.payload, ReactionSetPayload)
    assert draft.payload.existing_reaction is ReactionState.NONE
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
    request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id=f"prepare-post-{desired.value}",
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
            draft = await _reaction_draft(adapter, request)
            result = await adapter.execute_reaction(draft)
        finally:
            await browser.close()

    assert isinstance(draft.payload, ReactionSetPayload)
    assert draft.payload.existing_reaction is ReactionState.LIKE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is performed
    assert result.final_state == final_state


@pytest.mark.timeout(30)
async def test_reaction_refuses_state_drift_after_approval(tmp_path: Path) -> None:
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
    request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id="prepare-state-drift",
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
            result = await adapter.execute_reaction(await _reaction_draft(adapter, request))
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
    request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id="prepare-missing-execution-control",
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
            result = await adapter.execute_reaction(await _reaction_draft(adapter, request))
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
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-target-drift",
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
            result = await adapter.execute_comment(await _comment_draft(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "engagement_target_changed"
    assert "This must not be submitted." not in result.captured_text


@pytest.mark.timeout(30)
async def test_interrupted_final_comment_click_is_uncertain(tmp_path: Path) -> None:
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-interrupted-comment",
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
            result = await adapter.execute_comment(await _comment_draft(adapter, request))
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.UNCERTAIN
    assert result.performed is None
    assert result.final_state == "comment_outcome_unknown"


async def test_comment_asset_hash_is_revalidated_after_approval(tmp_path: Path) -> None:
    (tmp_path / "comment.png").write_bytes(b"confirmed")
    request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="prepare-hash-locked-comment",
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
            draft = await _comment_draft(adapter, request)
            (tmp_path / "comment.png").write_bytes(b"changed")
            with pytest.raises(InvalidTargetError, match="changed after confirmation"):
                await adapter.execute_comment(draft)
        finally:
            await browser.close()


def test_engagement_contract_rejects_empty_inputs_and_allows_native_discussion_aliases() -> None:
    with pytest.raises(ValidationError, match="requires text, a photo, or a GIF"):
        PostCommentPrepareInput(
            context_id="engagement-context",
            request_id="empty-comment",
            post_ref=POST_REF,
        )
    with pytest.raises(ValidationError, match="mentions require comment text"):
        PostCommentPrepareInput(
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
        PostCommentPrepareInput.model_validate(
            {
                "context_id": "engagement-context",
                "request_id": "threaded-reply-not-supported",
                "post_ref": POST_REF,
                "parent_comment_ref": COMMENT_REF,
                "text": "Threaded reply",
            }
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PostReactionPrepareInput.model_validate(
            {
                "context_id": "engagement-context",
                "request_id": "comment-reaction-not-supported",
                "post_ref": POST_REF,
                "comment_ref": COMMENT_REF,
                "desired_reaction": "like",
            }
        )
