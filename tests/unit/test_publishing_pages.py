from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl, ValidationError

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.pages import PostPublishingPage
from linkedin_mcp.domain.models import (
    ActionCommand,
    ActionOutcome,
    ActionPageResult,
    ActionType,
    CelebrationPostContent,
    CelebrationType,
    DocumentPostContent,
    EventFormat,
    EventPostContent,
    EventSpeakerInput,
    EventType,
    ExpertRequestCategory,
    ExpertRequestPostContent,
    HiringPostContent,
    ImagePostContent,
    PollDuration,
    PollPostContent,
    PostAudience,
    PostCollaboratorInput,
    PostCommentControl,
    PostCreateInput,
    PostCreatePayload,
    PostGroupTarget,
    PostImageAspectRatio,
    PostImageEditInput,
    PostImageFilter,
    PostImageInput,
    PostImageTagInput,
    PostMentionInput,
    TextPostContent,
    VideoCaptionMode,
    VideoPostContent,
)
from linkedin_mcp.errors import InvalidTargetError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
COMPOSER_HTML = (FIXTURES / "personal-post-composer.html").read_text()


class PublishingFixtureBrowser:
    def __init__(self, page: Page, *, composer_delay_ms: int = 0) -> None:
        self._page = page
        self._composer_delay_ms = composer_delay_ms
        self.fail_next_settings_click = False
        self.fail_after_post_click = False
        self.publish_outcome = "success"

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        async def fulfill(route: Route) -> None:
            await route.fulfill(status=200, content_type="text/html", body=COMPOSER_HTML)

        await page.route(url, fulfill, times=1)
        await page.goto(url)
        await page.evaluate(
            "values => {"
            " window.__linkedinMcpComposerDelayMs = values.delay;"
            " window.__linkedinMcpPublishOutcome = values.publishOutcome;"
            " }",
            {
                "delay": self._composer_delay_ms,
                "publishOutcome": self.publish_outcome,
            },
        )

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        del page
        label = await control.get_attribute("aria-label") or ""
        if self.fail_next_settings_click and label.startswith("Post settings"):
            self.fail_next_settings_click = False
            raise PlaywrightTimeoutError("fixture pre-submit timeout")
        await control.click()
        if self.fail_after_post_click and label == "Post":
            self.fail_after_post_click = False
            raise PlaywrightTimeoutError("fixture post-click timeout")


async def _action_command(
    adapter: PostPublishingPage,
    request: PostCreateInput,
) -> ActionCommand:
    capture = await adapter.inspect_post(request)
    assets = await adapter.snapshot_assets(request)
    return ActionCommand(
        action_type=ActionType.POST_CREATE,
        target=capture.target,
        payload=PostCreatePayload(
            content=request.content,
            audience=request.audience,
            group_target=request.group_target,
            comment_control=request.comment_control,
            brand_partnership=request.brand_partnership,
            collaborators=request.collaborators,
            scheduled_at=request.scheduled_at,
            assets=assets,
        ),
    )


@pytest.mark.timeout(15)
async def test_inspection_waits_through_the_current_visible_composer_loader(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-delayed-composer",
        content=TextPostContent(text="A delayed fixture composer."),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostPublishingPage(
            cast(
                BrowserManager,
                PublishingFixtureBrowser(page, composer_delay_ms=3_500),
            ),
            LocalAssetStore(tmp_path),
        )
        try:
            capture = await adapter.inspect_post(request)
        finally:
            await browser.close()

    assert capture.target.actor_profile_slug == "current-member"
    assert capture.current_state.startswith("personal_post_composer_ready:text")


@pytest.mark.timeout(30)
async def test_personal_text_post_action_verifies_new_stable_post(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-text-post",
        content=TextPostContent(
            text="A precise fixture post with @Alex.",
            mentions=(
                PostMentionInput(
                    token="@Alex",
                    profile_slug="alex-ray",
                ),
            ),
        ),
        audience=PostAudience.CONNECTIONS_ONLY,
        comment_control=PostCommentControl.NO_ONE,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostPublishingPage(
            cast(BrowserManager, PublishingFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _action_command(adapter, request)
            result = await adapter.perform_post(command)
        finally:
            await browser.close()

    assert command.target.actor_profile_slug == "current-member"
    assert command.target.actor_display_name == "Current Member"
    assert isinstance(command.payload, PostCreatePayload)
    assert command.payload.audience is PostAudience.CONNECTIONS_ONLY
    assert command.payload.comment_control is PostCommentControl.NO_ONE
    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("post_published:activity:")
    assert "A precise fixture post with @Alex." in result.captured_text


@pytest.mark.timeout(30)
async def test_pre_submit_timeout_is_a_verified_failure_not_an_uncertain_publish(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-pre-submit-timeout",
        content=TextPostContent(text="A fixture post that is never submitted."),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PublishingFixtureBrowser(page)
        adapter = PostPublishingPage(
            cast(BrowserManager, fixture_browser),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _action_command(adapter, request)
            fixture_browser.fail_next_settings_click = True
            result = await adapter.perform_post(command)
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "post_not_submitted"


@pytest.mark.timeout(30)
async def test_visible_success_alert_verifies_publish_after_post_click_timeout(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-post-click-timeout",
        content=TextPostContent(text="A visibly confirmed fixture post."),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PublishingFixtureBrowser(page)
        adapter = PostPublishingPage(
            cast(BrowserManager, fixture_browser),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _action_command(adapter, request)
            fixture_browser.fail_after_post_click = True
            result = await adapter.perform_post(command)
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.VERIFIED
    assert result.performed is True
    assert result.final_state.startswith("post_published:activity:")


@pytest.mark.timeout(30)
async def test_visible_failure_alert_returns_verified_non_publish(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-visible-publish-failure",
        content=TextPostContent(text="A fixture post that LinkedIn rejects."),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PublishingFixtureBrowser(page)
        adapter = PostPublishingPage(
            cast(BrowserManager, fixture_browser),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _action_command(adapter, request)
            fixture_browser.publish_outcome = "failure"
            result = await adapter.perform_post(command)
        finally:
            await browser.close()

    assert result.outcome is ActionOutcome.FAILED
    assert result.performed is False
    assert result.final_state == "post_not_published"


@pytest.mark.timeout(40)
async def test_photo_post_hashes_assets_and_applies_alt_text_and_exact_member_tag(
    tmp_path: Path,
) -> None:
    (tmp_path / "diagram.png").write_bytes(b"fixture-image")
    content = ImagePostContent(
        text="Architecture diagram",
        images=(
            PostImageInput(
                asset_ref="diagram.png",
                alt_text="A reliable architecture diagram",
                tags=(
                    PostImageTagInput(
                        profile_slug="alex-ray",
                        display_name="Alex Ray",
                    ),
                    PostImageTagInput(
                        company_slug="acme-cloud",
                        display_name="Acme Cloud",
                    ),
                ),
                edit=PostImageEditInput(
                    clockwise_quarter_turns=1,
                    flip_horizontal=True,
                    aspect_ratio=PostImageAspectRatio.SQUARE,
                    zoom=1.5,
                    straighten_degrees=4,
                    image_filter=PostImageFilter.STUDIO,
                    brightness=4,
                    contrast=-2,
                    saturation=3,
                    vignette=1,
                ),
            ),
        ),
    )
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-photo-post",
        content=content,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        adapter = PostPublishingPage(
            cast(BrowserManager, PublishingFixtureBrowser(page)),
            LocalAssetStore(tmp_path),
        )
        try:
            command = await _action_command(adapter, request)
            result = await adapter.perform_post(command)
        finally:
            await browser.close()

    assert isinstance(command.payload, PostCreatePayload)
    assert len(command.payload.assets) == 1
    assert command.payload.assets[0].asset_ref == "diagram.png"
    assert command.payload.assets[0].sha256 != "0" * 64
    assert command.payload.assets[0].alt_text == "A reliable architecture diagram"
    assert command.payload.assets[0].tagged_profile_slugs == ("alex-ray",)
    assert command.payload.assets[0].tagged_company_slugs == ("acme-cloud",)
    assert result.outcome is ActionOutcome.VERIFIED


@pytest.mark.timeout(40)
async def test_video_document_and_poll_modes_cover_all_structured_composer_options(
    tmp_path: Path,
) -> None:
    (tmp_path / "demo.mp4").write_bytes(b"v" * (75 * 1024))
    (tmp_path / "thumb.png").write_bytes(b"thumbnail")
    (tmp_path / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nFixture\n")
    (tmp_path / "guide.pdf").write_bytes(b"%PDF-fixture")
    requests = (
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-video-post",
            content=VideoPostContent(
                text="A fixture video",
                video_asset_ref="demo.mp4",
                thumbnail_asset_ref="thumb.png",
                caption_mode=VideoCaptionMode.FILE,
                caption_asset_ref="captions.srt",
            ),
        ),
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-document-post",
            content=DocumentPostContent(
                text="A fixture document",
                document_asset_ref="guide.pdf",
                document_title="Reliable Systems Guide",
            ),
        ),
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-poll-post",
            content=PollPostContent(
                text="Choose one",
                question="Which property matters most?",
                options=("Reliability", "Latency", "Cost", "Simplicity"),
                duration=PollDuration.TWO_WEEKS,
            ),
        ),
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        results: list[ActionPageResult] = []
        drafts: list[ActionCommand] = []
        try:
            for request in requests:
                page = await browser.new_page()
                adapter = PostPublishingPage(
                    cast(BrowserManager, PublishingFixtureBrowser(page)),
                    LocalAssetStore(tmp_path),
                )
                command = await _action_command(adapter, request)
                drafts.append(command)
                results.append(await adapter.perform_post(command))
                await page.close()
        finally:
            await browser.close()

    payloads = [command.payload for command in drafts]
    assert all(isinstance(payload, PostCreatePayload) for payload in payloads)
    assert [
        len(payload.assets) for payload in payloads if isinstance(payload, PostCreatePayload)
    ] == [3, 1, 0]
    assert all(result.outcome is ActionOutcome.VERIFIED for result in results)
    assert all(result.final_state.startswith("post_published:") for result in results)


@pytest.mark.timeout(60)
async def test_celebration_event_hiring_and_expert_modes_follow_current_visible_flows(
    tmp_path: Path,
) -> None:
    (tmp_path / "celebration.webp").write_bytes(b"celebration")
    (tmp_path / "event-cover.png").write_bytes(b"event-cover")
    start_at = datetime.now(UTC) + timedelta(days=2)
    requests = (
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-celebration-post",
            content=CelebrationPostContent(
                text="We shipped the reliability project.",
                celebration_type=CelebrationType.PROJECT_LAUNCH,
                template_index=None,
                image_asset_ref="celebration.webp",
                image_alt_text="Team celebrating a project launch",
            ),
        ),
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-event-post",
            content=EventPostContent(
                text="Join our reliability event.",
                event_type=EventType.ONLINE,
                event_format=EventFormat.EXTERNAL_LINK,
                event_name="Reliable Systems Live",
                timezone_label="(UTC+05:30) Chennai, Kolkata, Mumbai, New Delhi",
                start_at=start_at,
                end_at=start_at + timedelta(hours=1),
                external_url=HttpUrl("https://example.com/events/reliable-systems"),
                description="A practical live session about bounded recovery.",
                speakers=(
                    EventSpeakerInput(
                        profile_slug="alex-ray",
                        display_name="Alex Ray",
                    ),
                ),
                cover_asset_ref="event-cover.png",
                cover_alt_text="Reliable Systems Live cover",
            ),
        ),
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-hiring-post",
            content=HiringPostContent(
                text="We are hiring a Staff Engineer.",
                company_name="Acme Cloud",
                job_id="444555666",
                job_title="Staff Engineer",
            ),
        ),
        PostCreateInput(
            context_id="publishing-context",
            request_id="action-expert-request",
            content=ExpertRequestPostContent(
                text="Looking for an expert to review our service design.",
                category=ExpertRequestCategory.DESIGN,
                location_label="Bengaluru, Karnataka, India",
            ),
        ),
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        drafts: list[ActionCommand] = []
        results: list[ActionPageResult] = []
        try:
            for request in requests:
                page = await browser.new_page()
                adapter = PostPublishingPage(
                    cast(BrowserManager, PublishingFixtureBrowser(page)),
                    LocalAssetStore(tmp_path),
                )
                command = await _action_command(adapter, request)
                drafts.append(command)
                results.append(await adapter.perform_post(command))
                await page.close()
        finally:
            await browser.close()

    assert [
        tuple(asset.role.value for asset in command.payload.assets)
        for command in drafts
        if isinstance(command.payload, PostCreatePayload)
    ] == [
        ("celebration_image",),
        ("event_cover_image",),
        (),
        (),
    ]
    assert all(result.outcome is ActionOutcome.VERIFIED for result in results)
    assert all(result.final_state.startswith("post_published:") for result in results)


@pytest.mark.timeout(40)
async def test_group_brand_partnership_and_collaborators_are_exactly_bound(
    tmp_path: Path,
) -> None:
    request = PostCreateInput(
        context_id="publishing-context",
        request_id="action-group-collaboration-post",
        content=TextPostContent(text="A precisely targeted fixture post."),
        audience=PostAudience.GROUP,
        group_target=PostGroupTarget(
            group_id="123456789",
            display_name="Reliable Systems Community",
        ),
        brand_partnership=False,
    )
    collaborative = PostCreateInput(
        context_id="publishing-context",
        request_id="action-public-collaboration-post",
        content=TextPostContent(text="A public collaborative fixture post."),
        brand_partnership=True,
        collaborators=(
            PostCollaboratorInput(
                profile_slug="alex-ray",
                display_name="Alex Ray",
            ),
            PostCollaboratorInput(
                company_slug="acme-cloud",
                display_name="Acme Cloud",
            ),
        ),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            results: list[ActionPageResult] = []
            drafts: list[ActionCommand] = []
            for item in (request, collaborative):
                page = await browser.new_page()
                adapter = PostPublishingPage(
                    cast(BrowserManager, PublishingFixtureBrowser(page)),
                    LocalAssetStore(tmp_path),
                )
                command = await _action_command(adapter, item)
                drafts.append(command)
                results.append(await adapter.perform_post(command))
                await page.close()
        finally:
            await browser.close()

    assert isinstance(drafts[0].payload, PostCreatePayload)
    assert drafts[0].payload.group_target == request.group_target
    assert isinstance(drafts[1].payload, PostCreatePayload)
    assert drafts[1].payload.brand_partnership is True
    assert drafts[1].payload.collaborators == collaborative.collaborators
    assert all(result.outcome is ActionOutcome.VERIFIED for result in results)


@pytest.mark.timeout(30)
async def test_link_preview_removal_and_scheduling_have_visible_postconditions(
    tmp_path: Path,
) -> None:
    immediate = PostCreateInput(
        context_id="publishing-context",
        request_id="action-link-post",
        content=TextPostContent(
            text="Read https://example.com/guide",
            link_url=HttpUrl("https://example.com/guide"),
            show_link_preview=False,
        ),
    )
    scheduled = PostCreateInput(
        context_id="publishing-context",
        request_id="action-scheduled-post",
        content=TextPostContent(text="A scheduled fixture post"),
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            results: list[ActionPageResult] = []
            for request in (immediate, scheduled):
                page = await browser.new_page()
                adapter = PostPublishingPage(
                    cast(BrowserManager, PublishingFixtureBrowser(page)),
                    LocalAssetStore(tmp_path),
                )
                results.append(await adapter.perform_post(await _action_command(adapter, request)))
                await page.close()
        finally:
            await browser.close()

    assert results[0].outcome is ActionOutcome.VERIFIED
    assert results[1].outcome is ActionOutcome.VERIFIED
    assert results[1].final_state == "post_scheduled"
    assert "Post scheduled" in results[1].captured_text


async def test_asset_store_rejects_traversal_type_drift_and_changed_bytes(
    tmp_path: Path,
) -> None:
    (tmp_path / "safe.png").write_bytes(b"first")
    (tmp_path / "notes.txt").write_text("wrong type")
    store = LocalAssetStore(tmp_path)
    content = ImagePostContent(
        text="Safe asset",
        images=(PostImageInput(asset_ref="safe.png"),),
    )
    snapshots = await store.snapshot(content)
    payload = PostCreatePayload(
        content=content,
        audience=PostAudience.ANYONE,
        comment_control=PostCommentControl.ANYONE,
        assets=snapshots,
    )
    assert (await store.verify(payload))["safe.png"] == tmp_path / "safe.png"

    (tmp_path / "safe.png").write_bytes(b"changed")
    with pytest.raises(InvalidTargetError, match="changed during the action"):
        await store.verify(payload)
    with pytest.raises(InvalidTargetError, match="file type"):
        await store.snapshot(
            ImagePostContent(
                text="Wrong type",
                images=(PostImageInput(asset_ref="notes.txt"),),
            )
        )


def test_post_create_contract_rejects_ambiguous_or_unverifiable_options() -> None:
    with pytest.raises(ValidationError, match="requires text"):
        TextPostContent()
    with pytest.raises(ValidationError, match="exactly once"):
        TextPostContent(
            text="@Alex and @Alex",
            mentions=(
                PostMentionInput(
                    token="@Alex",
                    profile_slug="alex-ray",
                ),
            ),
        )
    with pytest.raises(ValidationError, match="Poll options must be unique"):
        PollPostContent(
            question="Choose",
            options=("One", "one"),
        )
    with pytest.raises(ValidationError, match="timezone"):
        PostCreateInput(
            context_id="publishing-context",
            request_id="naive-schedule",
            content=TextPostContent(text="Schedule"),
            scheduled_at=datetime.now(),  # noqa: DTZ005 - intentionally naive validation case
        )
    with pytest.raises(ValidationError, match="group_target"):
        PostCreateInput(
            context_id="publishing-context",
            request_id="group-without-target",
            content=TextPostContent(text="Group post"),
            audience=PostAudience.GROUP,
        )
    with pytest.raises(ValidationError, match="Anyone"):
        PostCreateInput(
            context_id="publishing-context",
            request_id="private-brand-post",
            content=TextPostContent(text="Brand post"),
            audience=PostAudience.CONNECTIONS_ONLY,
            brand_partnership=True,
        )
    with pytest.raises(ValidationError, match="does not schedule"):
        PostCreateInput(
            context_id="publishing-context",
            request_id="scheduled-hiring-post",
            content=HiringPostContent(
                text="We are hiring.",
                company_name="Acme Cloud",
                job_id="444555666",
                job_title="Staff Engineer",
            ),
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
        )
    with pytest.raises(ValidationError, match="exactly one"):
        CelebrationPostContent(
            text="Celebration",
            celebration_type=CelebrationType.NEW_POSITION,
            template_index=1,
            image_asset_ref="celebration.png",
        )
    with pytest.raises(ValidationError, match="external_url"):
        EventPostContent(
            text="Event",
            event_type=EventType.ONLINE,
            event_format=EventFormat.EXTERNAL_LINK,
            event_name="Event",
            timezone_label="UTC",
            start_at=datetime.now(UTC) + timedelta(days=1),
            description="Description",
        )
    with pytest.raises(ValidationError, match="25 to 750"):
        ExpertRequestPostContent(
            text="Too short",
            category=ExpertRequestCategory.OTHER,
            location_label="Bengaluru, Karnataka, India",
        )


def test_photo_contract_allows_linkedin_duplicates_and_binds_tag_identity() -> None:
    post = ImagePostContent(
        text="Use one image twice.",
        images=(
            PostImageInput(asset_ref="diagram.png"),
            PostImageInput(asset_ref="diagram.png"),
        ),
    )
    assert len(post.images) == 2
    with pytest.raises(ValidationError, match="exactly one"):
        PostImageTagInput(display_name="Ambiguous")
    with pytest.raises(ValidationError, match="exactly one"):
        PostImageTagInput(
            display_name="Ambiguous",
            profile_slug="alex-ray",
            company_slug="acme-cloud",
        )
