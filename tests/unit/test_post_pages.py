from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.async_api import Locator, Page, Route, async_playwright
from pydantic import HttpUrl, ValidationError

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.posts.comments.list.evidence import source_from_post_comments
from linkedin_mcp.tools.posts.comments.list.models import (
    CommentSort,
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.get.evidence import source_from_post
from linkedin_mcp.tools.posts.get.models import (
    PostAuthorType,
    PostDetailCoverage,
    PostGetInput,
    PostObservation,
    PostPollState,
    ReactionState,
)
from linkedin_mcp.tools.posts.get.models import (
    PostContentType as DetailPostContentType,
)
from linkedin_mcp.tools.posts.get.page import PostDetailPage
from linkedin_mcp.tools.posts.search.evidence import source_from_post_search
from linkedin_mcp.tools.posts.search.models import (
    PostContentType as SearchPostContentType,
)
from linkedin_mcp.tools.posts.search.models import (
    PostSearchContentType,
    PostSearchDate,
    PostSearchFilters,
    PostSearchInput,
    PostSearchPostedBy,
    PostSearchSort,
    StopReason,
)
from linkedin_mcp.tools.posts.search.page import PostSearchPage
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.urls import post_reference_from_value
from tests.support.playwright import adapt_browser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
POST_REF = "activity:7312345678901234567"
VIDEO_POST_REF = "ugc-post:7312345678901234568"
DOCUMENT_POST_REF = "share:7312345678901234569"
ARTICLE_POST_REF = "activity:7312345678901234570"
CLOSED_POLL_POST_REF = "activity:7312345678901234571"
OPEN_POLL_POST_REF = "ugc-post:7312345678901234572"
REPOST_REF = "activity:7312345678901234573"
REPOST_ORIGINAL_REF = "share:7312345678901234574"
TEXT_POST_REF = "activity:7312345678901234575"
LIVE_VIDEO_POST_REF = "ugc-post:7312345678901234576"


class PostFixtureBrowser:
    def __init__(
        self,
        page: Page,
        *,
        detail_fixtures: dict[str, str] | None = None,
    ) -> None:
        self._page = page
        self.navigations: list[str] = []
        self._routed = False
        self._detail_fixtures = detail_fixtures or {
            POST_REF: "posts/latest/detail-image.html",
        }

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        if not self._routed:
            await page.route("**/*", self._fulfill)
            self._routed = True
        await page.goto(url, wait_until="domcontentloaded")

    async def _fulfill(self, route: Route) -> None:
        request = route.request
        if request.resource_type != "document":
            await route.fulfill(status=204, body="")
            return
        path = urlsplit(request.url).path
        if path.startswith("/search/results/content"):
            fixture = "posts/latest/search.html"
        else:
            post_ref = post_reference_from_value(request.url)
            fixture = self._detail_fixtures.get(post_ref or "")
            if fixture is None:
                raise AssertionError(f"No post-detail fixture registered for {post_ref!r}.")
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=(FIXTURES / fixture).read_text(encoding="utf-8"),
        )

    async def click_visible_control(self, page: Page, control: object) -> None:
        del page
        await cast(Locator, control).click()

    async def navigate_via_visible_control(self, page: Page, control: Locator) -> str:
        await control.click()
        await page.wait_for_load_state("domcontentloaded")
        return page.url

    async def assert_safe(self, page: Page) -> None:
        del page


class StaticPostFixtureBrowser:
    def __init__(self, page: Page, html: str) -> None:
        self._page = page
        self._html = html
        self._routed = False

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        if not self._routed:
            await page.route("**/*", self._fulfill)
            self._routed = True
        await page.goto(url, wait_until="domcontentloaded")

    async def _fulfill(self, route: Route) -> None:
        if route.request.resource_type == "document":
            await route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=self._html,
            )
        else:
            await route.fulfill(status=204, body="")

    async def click_visible_control(self, page: Page, control: object) -> None:
        del page
        await cast(Locator, control).click()

    async def assert_safe(self, page: Page) -> None:
        del page


def _decoded_values(query: dict[str, list[str]], key: str) -> list[str]:
    return cast(list[str], json.loads(query[key][0]))


def test_post_fixture_manifest_locks_current_visible_filter_surface() -> None:
    manifest = cast(
        dict[str, object],
        json.loads((FIXTURES / "posts/latest/manifest.json").read_text(encoding="utf-8")),
    )

    assert manifest["provenance"] == "mock_verified"
    assert manifest["verified_at"] == "2026-08-05"
    assert manifest["contains_live_data"] is False
    assert manifest["filter_sections"] == [
        "Sort by",
        "Date posted",
        "Content type",
        "From member",
        "From company",
        "Posted by",
        "Mentioning member",
        "Mentioning company",
        "Author industry",
        "Author company",
        "Author Keywords",
    ]
    assert manifest["content_type_choices"] == [
        "Videos",
        "Images",
        "Job posts",
        "Live videos",
        "Documents",
    ]
    assert manifest["posted_by_choices"] == [
        "Me",
        "1st connections",
        "People you follow",
    ]
    search_contract = cast(dict[str, object], manifest["search_card_contract"])
    assert "compact region" in cast(str, search_contract["header"])
    assert "keyboard activation" in cast(str, search_contract["body"])
    assert "Reaction button state" in cast(str, search_contract["engagement"])
    assert "exclude author avatars" in cast(str, search_contract["content_type"])
    assert search_contract["unsupported_identity_fixture"] == ("search-unsupported-author.html")
    detail_contract = cast(dict[str, object], manifest["detail_contract"])
    assert detail_contract["stable_reference_action"] == "Copy link to post"
    assert detail_contract["body"] == '[data-testid="expandable-text-box"]'
    assert detail_contract["poll_states"] == [
        "open radio options",
        "closed percentages and Poll closed",
    ]
    engagement_contract = cast(dict[str, object], manifest["engagement_contract"])
    assert engagement_contract["current_thread_layout_fixture"] == ("comments-flat-threads.html")
    assert "nearest preceding root" in cast(str, engagement_contract["current_thread_layout"])
    assert manifest["detail_fixtures"] == [
        "detail-text.html",
        "detail-image.html",
        "detail-video.html",
        "detail-live-video.html",
        "detail-document.html",
        "detail-article.html",
        "detail-poll-open.html",
        "detail-poll-closed.html",
        "detail-repost.html",
        "detail-repost-original.html",
    ]


def test_post_contracts_reject_unsafe_or_conflicting_requests() -> None:
    assert tuple(PostSearchContentType) == (
        PostSearchContentType.VIDEOS,
        PostSearchContentType.IMAGES,
        PostSearchContentType.JOB_POSTS,
        PostSearchContentType.LIVE_VIDEOS,
        PostSearchContentType.DOCUMENTS,
    )
    assert tuple(PostSearchPostedBy) == (
        PostSearchPostedBy.ME,
        PostSearchPostedBy.FIRST_CONNECTIONS,
        PostSearchPostedBy.PEOPLE_YOU_FOLLOW,
    )
    assert {
        SearchPostContentType.LINK,
        SearchPostContentType.LIVE_VIDEO,
        SearchPostContentType.REPOST,
    }.issubset(set(SearchPostContentType))
    post_schema = PostObservation.model_json_schema()
    assert {
        "displayed_post_ref",
        "poll",
        "reshared_post",
        "viewer_reaction",
        "coverage",
    }.issubset(post_schema["properties"])

    with pytest.raises(ValidationError, match="requires query"):
        PostSearchInput(context_id="context-1", request_id="empty-post-search")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PostSearchFilters.model_validate({"content_types": ["posts"]})

    with pytest.raises(ValidationError, match="cannot contain duplicate"):
        PostSearchFilters(from_company_names=("Acme Cloud", "acme cloud"))

    with pytest.raises(ValidationError, match="at most ten combined"):
        PostSearchFilters(
            mentioning_member_ids=tuple(f"member-{index}" for index in range(5)),
            mentioning_member_names=tuple(f"Member {index}" for index in range(6)),
        )

    with pytest.raises(ValueError, match="Post search page bound"):
        PostSearchPage(cast(LinkedInPlaywright, object()), max_pages=0)
    with pytest.raises(ValueError, match="Comment expansion bound"):
        PostCommentsPage(cast(LinkedInPlaywright, object()), max_expansion_rounds=-1)
    with pytest.raises(ValidationError, match="conflict with pages_visited"):
        PostDetailCoverage(
            requested_post_ref=POST_REF,
            displayed_post_ref=POST_REF,
            pages_visited=2,
            source_urls=(
                HttpUrl(
                    "https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"
                ),
            ),
            text_expanded=True,
            attachment_count=0,
            link_count=0,
            mention_count=0,
            hashtag_count=0,
            poll_present=False,
            reshared_post_present=False,
            captured_at=datetime.now(UTC),
        )


def test_post_search_url_encodes_every_direct_visible_filter_family() -> None:
    request = PostSearchInput(
        context_id="context-1",
        request_id="post-direct-filters",
        query='"reliable systems" AND Python',
        filters=PostSearchFilters(
            sort_by=PostSearchSort.LATEST,
            date_posted=PostSearchDate.PAST_WEEK,
            content_type=PostSearchContentType.LIVE_VIDEOS,
            from_member_ids=("ACoJane",),
            from_company_ids=("12345",),
            posted_by=tuple(PostSearchPostedBy),
            mentioning_member_ids=("ACoAlex",),
            mentioning_company_ids=("67890",),
            author_industry_ids=("4",),
            author_company_ids=("12345",),
            author_keywords="Staff Engineer",
        ),
    )

    query = parse_qs(urlsplit(PostSearchPage.build_url(request, page_index=2)).query)

    assert query["origin"] == ["FACETED_SEARCH"]
    assert query["page"] == ["2"]
    assert query["keywords"] == ['"reliable systems" AND Python']
    assert _decoded_values(query, "sortBy") == ["date_posted"]
    assert _decoded_values(query, "datePosted") == ["past-week"]
    assert _decoded_values(query, "contentType") == ["liveVideos"]
    assert _decoded_values(query, "fromMember") == ["ACoJane"]
    assert _decoded_values(query, "fromOrganization") == ["12345"]
    assert _decoded_values(query, "postedBy") == ["me", "first", "following"]
    assert _decoded_values(query, "mentionsMember") == ["ACoAlex"]
    assert _decoded_values(query, "mentionsOrganization") == ["67890"]
    assert _decoded_values(query, "authorIndustry") == ["4"]
    assert _decoded_values(query, "authorCompany") == ["12345"]
    assert json.loads(query["authorJobTitle"][0]) == "Staff Engineer"


@pytest.mark.parametrize(
    ("content_type", "submitted_value"),
    (
        (PostSearchContentType.VIDEOS, "videos"),
        (PostSearchContentType.IMAGES, "photos"),
        (PostSearchContentType.JOB_POSTS, "jobs"),
        (PostSearchContentType.LIVE_VIDEOS, "liveVideos"),
        (PostSearchContentType.DOCUMENTS, "documents"),
    ),
)
def test_post_search_encodes_every_current_content_type(
    content_type: PostSearchContentType,
    submitted_value: str,
) -> None:
    request = PostSearchInput(
        context_id="context-1",
        request_id=f"post-content-{content_type.value}",
        filters=PostSearchFilters(content_type=content_type),
    )

    query = parse_qs(urlsplit(PostSearchPage.build_url(request, page_index=1)).query)

    assert _decoded_values(query, "contentType") == [submitted_value]


@pytest.mark.timeout(30)
async def test_post_search_resolves_all_named_facets_and_extracts_stable_results() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PostFixtureBrowser(page)
        collector = PostSearchPage(adapt_browser(fixture_browser), max_pages=2)
        request = PostSearchInput(
            context_id="context-1",
            request_id="post-named-filters",
            query="python reliability",
            filters=PostSearchFilters(
                from_member_names=("Jane Doe",),
                from_company_names=("Acme Cloud",),
                mentioning_member_names=("Alex Ray",),
                mentioning_company_names=("Example Labs",),
                author_industry_names=("Software Development",),
                author_company_names=("Acme Cloud",),
            ),
            page_size=1,
        )
        try:
            posts, coverage, captured_text, source_url = await collector.collect(request)
        finally:
            await browser.close()

    assert len(posts) == 1
    assert posts[0].post_ref == POST_REF
    assert posts[0].author.profile_slug == "jane-doe"
    assert posts[0].author.headline == "Staff Engineer at Acme Cloud"
    assert posts[0].author.relationship_text == "1st"
    assert posts[0].posted_at_text == "2h • Edited •"
    assert posts[0].text is not None and "#python" in posts[0].text
    assert "… more" not in posts[0].text
    assert posts[0].content_type is SearchPostContentType.TEXT
    assert posts[0].reaction_count_text == "12"
    assert posts[0].comment_count_text == "3"
    assert posts[0].repost_count_text == "1"
    assert coverage.pages_visited == 1
    assert coverage.unsupported_result_count == 1
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert posts[0].visible_text in captured_text
    assert source_url == fixture_browser.navigations[-1]
    assert len(fixture_browser.navigations) == 2

    query = parse_qs(urlsplit(source_url).query)
    assert _decoded_values(query, "fromMember") == ["ACoJane"]
    assert _decoded_values(query, "fromOrganization") == ["12345"]
    assert _decoded_values(query, "mentionsMember") == ["ACoAlex"]
    assert _decoded_values(query, "mentionsOrganization") == ["67890"]
    assert _decoded_values(query, "authorIndustry") == ["4"]
    assert _decoded_values(query, "authorCompany") == ["12345"]
    source = source_from_post_search(
        source_url=source_url,
        captured_text=captured_text,
        posts=posts,
        coverage=coverage,
    )
    assert source.source_type.value == "linkedin_post_search"


@pytest.mark.timeout(30)
async def test_post_search_inventories_virtualized_prefix_before_expanding_cards() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PostFixtureBrowser(page)
        collector = PostSearchPage(adapt_browser(fixture_browser), max_pages=1)
        try:
            posts, coverage, captured_text, _ = await collector.collect(
                PostSearchInput(
                    context_id="context-1",
                    request_id="post-virtualized-prefix",
                    query="reliability",
                    page_size=2,
                ),
                result_limit=2,
            )
        finally:
            await browser.close()

    assert [post.post_ref for post in posts] == [
        POST_REF,
        "activity:7312345678901234999",
    ]
    assert [post.author.name for post in posts] == ["Jane Doe", "Acme Cloud"]
    assert coverage.unsupported_result_count == 1
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert all(post.visible_text in captured_text for post in posts)


@pytest.mark.timeout(20)
async def test_post_search_waits_for_async_initial_results() -> None:
    html = """
    <!doctype html>
    <html><body><main>
      <h1>Posts</h1>
      <div id="results"></div>
      <template id="late-result">
        <article data-post-urn="urn:li:activity:7312345678901234777">
          <div>
            <a href="/in/late-author-/">Late Author</a>
            <p>Reliability Engineer</p>
            <p>1h •</p>
            <button aria-label="Open control menu for post by Late Author"></button>
          </div>
          <p data-testid="expandable-text-box">Late-rendered reliability post.</p>
          <button aria-label="Reaction button state: no reaction"></button>
          <button aria-label="Comment"></button>
          <button aria-label="Repost"></button>
        </article>
      </template>
    </main>
    <script>
      setTimeout(() => {
        document.querySelector("#results").append(
          document.querySelector("#late-result").content.cloneNode(true)
        );
      }, 700);
    </script></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PostSearchPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_pages=1,
        )
        try:
            posts, coverage, _, _ = await collector.collect(
                PostSearchInput(
                    context_id="context-1",
                    request_id="async-post-results",
                    query="reliability",
                    page_size=1,
                )
            )
        finally:
            await browser.close()

    assert [post.post_ref for post in posts] == ["activity:7312345678901234777"]
    assert posts[0].author.profile_slug == "late-author-"
    assert coverage.stop_reason is StopReason.RESULT_LIMIT


@pytest.mark.timeout(20)
async def test_post_search_only_completes_empty_on_visible_end_state() -> None:
    html = "<html><body><main><h1>Posts</h1><p>No matching posts found.</p></main></body></html>"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PostSearchPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_pages=1,
        )
        try:
            posts, coverage, _, _ = await collector.collect(
                PostSearchInput(
                    context_id="context-1",
                    request_id="empty-post-results",
                    query="impossible",
                )
            )
        finally:
            await browser.close()

    assert posts == ()
    assert coverage.stop_reason is StopReason.NO_NEW_RESULTS


@pytest.mark.timeout(20)
async def test_post_search_classifies_selected_card_with_unsupported_author_identity() -> None:
    html = (FIXTURES / "posts/latest/search-unsupported-author.html").read_text(encoding="utf-8")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PostSearchPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_pages=1,
        )
        try:
            posts, coverage, captured_text, _ = await collector.collect(
                PostSearchInput(
                    context_id="context-1",
                    request_id="unsupported-post-author",
                    query="reliability",
                    page_size=2,
                )
            )
        finally:
            await browser.close()

    assert [post.post_ref for post in posts] == ["activity:7312345678901234889"]
    assert posts[0].visible_text in captured_text
    assert coverage.result_count == 1
    assert coverage.unsupported_result_count == 1
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE


@pytest.mark.timeout(20)
async def test_post_search_classifies_delayed_linkedin_short_link_as_unsupported() -> None:
    html = """
    <!doctype html>
    <html lang="en">
      <body>
        <main>
          <div role="listitem">
            <a href="/in/jane-doe/">Jane Doe</a>
            <div>1h</div>
            <button data-menu aria-label="Open control menu for post by Jane Doe"></button>
            <div class="feed-shared-update-v2__description">Opaque short-link post.</div>
            <button aria-label="React Like" aria-pressed="false">Like</button>
          </div>
        </main>
        <script>
          document.querySelector('[data-menu]').addEventListener('click', () => {
            const item = document.createElement('p');
            item.textContent = 'Copy link to post';
            item.addEventListener('click', () => {
              setTimeout(
                () => navigator.clipboard.writeText('https://lnkd.in/p/fixture-token'),
                350,
              );
            });
            document.body.append(item);
          });
        </script>
      </body>
    </html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PostSearchPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_pages=1,
        )
        try:
            posts, coverage, _, _ = await collector.collect(
                PostSearchInput(
                    context_id="context-1",
                    request_id="delayed-short-link",
                    query="opaque",
                    page_size=2,
                )
            )
        finally:
            await browser.close()

    assert posts == ()
    assert coverage.result_count == 0
    assert coverage.unsupported_result_count == 1
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE


@pytest.mark.timeout(30)
async def test_post_detail_image_preserves_current_visible_contract_and_evidence() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        detail_page = await browser.new_page()
        detail_browser = PostFixtureBrowser(detail_page)
        reader = PostDetailPage(adapt_browser(detail_browser))
        try:
            post = await reader.read(
                PostGetInput(
                    context_id="context-1",
                    request_id="post-detail-1",
                    post_ref=POST_REF,
                )
            )
        finally:
            await detail_page.close()
            await browser.close()

    assert post.post_ref == POST_REF
    assert post.displayed_post_ref == POST_REF
    assert post.author.author_type is PostAuthorType.MEMBER
    assert post.author.profile_slug == "jane-doe"
    assert post.author.headline == "Staff Engineer at Acme Cloud"
    assert post.author.relationship_text == "1st"
    assert post.author.verified is True
    assert post.posted_at_text == "2mo • Edited"
    assert post.edited is True
    assert post.visibility_text == "Visibility: Global"
    assert post.content_type is DetailPostContentType.IMAGE
    assert len(post.attachments) == 1
    assert post.attachments[0].label == "Reliability architecture diagram"
    assert post.links[0].label == "Read the guide"
    assert post.hashtags == ("#python",)
    assert {mention.label for mention in post.mentions} == {"Alex Ray", "Acme Cloud"}
    assert post.viewer_reaction is ReactionState.LIKE
    assert post.reaction_count_text == "128"
    assert post.comment_count_text == "34"
    assert post.repost_count_text == "7"
    assert post.impression_count_text == "49 impressions"
    assert post.comments_enabled is True
    assert post.text is not None and "recovery checks" in post.text
    assert post.coverage.pages_visited == 1
    assert post.coverage.text_expanded is True
    assert post.coverage.attachment_count == 1
    assert post.coverage.source_urls == (post.post_url,)
    assert all(evidence.quote in post.visible_text for evidence in post.evidence)
    assert all(evidence.captured_at == post.captured_at for evidence in post.evidence)
    assert source_from_post(post).source_type.value == "linkedin_post"
    mismatched_source = post.model_copy(
        update={
            "evidence": tuple(
                evidence.model_copy(
                    update={"source_url": HttpUrl("https://www.linkedin.com/feed/")}
                )
                for evidence in post.evidence
            )
        }
    )
    with pytest.raises(ParserDriftError, match="not an exact visible substring"):
        source_from_post(mismatched_source)


@pytest.mark.timeout(30)
async def test_post_detail_extracts_current_video_document_article_and_poll_variants() -> None:
    fixtures = {
        TEXT_POST_REF: "posts/latest/detail-text.html",
        VIDEO_POST_REF: "posts/latest/detail-video.html",
        LIVE_VIDEO_POST_REF: "posts/latest/detail-live-video.html",
        DOCUMENT_POST_REF: "posts/latest/detail-document.html",
        ARTICLE_POST_REF: "posts/latest/detail-article.html",
        CLOSED_POLL_POST_REF: "posts/latest/detail-poll-closed.html",
        OPEN_POLL_POST_REF: "posts/latest/detail-poll-open.html",
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PostFixtureBrowser(page, detail_fixtures=fixtures)
        reader = PostDetailPage(adapt_browser(fixture_browser))
        try:
            observations = {
                post_ref: await reader.read(
                    PostGetInput(
                        context_id="context-1",
                        request_id=f"detail-{post_ref.replace(':', '-')}",
                        post_ref=post_ref,
                    )
                )
                for post_ref in fixtures
            }
        finally:
            await browser.close()

    text_post = observations[TEXT_POST_REF]
    assert text_post.content_type is DetailPostContentType.TEXT
    assert text_post.attachments == ()
    assert text_post.hashtags == ("#reliability",)
    assert text_post.comments_enabled is False

    video = observations[VIDEO_POST_REF]
    assert video.content_type is DetailPostContentType.VIDEO
    assert video.author.author_type is PostAuthorType.COMPANY
    assert video.author.company_slug == "example-labs"
    assert video.author.follower_count_text == "42,115 followers"
    assert len(video.attachments) == 1
    assert str(video.attachments[0].url) == ("https://media.example.test/reliability-demo.mp4")
    assert str(video.attachments[0].preview_url) == (
        "https://media.example.test/reliability-demo.jpg"
    )
    assert video.viewer_reaction is ReactionState.NONE

    live_video = observations[LIVE_VIDEO_POST_REF]
    assert live_video.content_type is DetailPostContentType.LIVE_VIDEO
    assert len(live_video.attachments) == 1
    assert live_video.attachments[0].content_type is DetailPostContentType.LIVE_VIDEO

    document = observations[DOCUMENT_POST_REF]
    assert document.content_type is DetailPostContentType.DOCUMENT
    assert document.author.profile_slug == "morgan-lee-"
    assert document.author.relationship_text == "3rd+"
    assert document.visibility_text == "Visibility: Connections only"
    assert len(document.attachments) == 1
    assert document.attachments[0].page_count == 5
    assert document.attachments[0].label == "Reliable systems handbook"
    assert document.viewer_reaction is ReactionState.INSIGHTFUL

    article = observations[ARTICLE_POST_REF]
    assert article.content_type is DetailPostContentType.ARTICLE
    assert len(article.attachments) == 1
    assert article.attachments[0].label == "Designing Recovery Before Failure"
    assert article.attachments[0].preview_url is not None
    assert [mention.label for mention in article.mentions] == ["Sam Kim"]
    assert article.repost_count_text is None

    closed_poll = observations[CLOSED_POLL_POST_REF]
    assert closed_poll.content_type is DetailPostContentType.POLL
    assert closed_poll.poll is not None
    assert closed_poll.poll.question == "Which reliability topic should we cover next?"
    assert closed_poll.poll.state is PostPollState.CLOSED
    assert closed_poll.poll.state_text == "Poll closed"
    assert closed_poll.poll.total_votes_text == "5 votes"
    assert [option.text for option in closed_poll.poll.options] == [
        "Incident response",
        "Load shedding",
        "Data recovery",
        "Capacity planning",
    ]
    assert [option.percentage_text for option in closed_poll.poll.options] == [
        "40 %",
        "20 %",
        "20 %",
        "20 %",
    ]

    open_poll = observations[OPEN_POLL_POST_REF]
    assert open_poll.content_type is DetailPostContentType.POLL
    assert open_poll.author.author_type is PostAuthorType.COMPANY
    assert open_poll.poll is not None
    assert open_poll.poll.question == "What should we demonstrate live?"
    assert open_poll.poll.state is PostPollState.OPEN
    assert open_poll.poll.viewer_has_voted is False
    assert [option.text for option in open_poll.poll.options] == [
        "Failover testing",
        "Queue backpressure",
        "Safe deployment",
    ]

    assert all(
        observation.coverage.pages_visited == 1
        and observation.coverage.truncated is False
        and source_from_post(observation).source_type.value == "linkedin_post"
        for observation in observations.values()
    )


@pytest.mark.timeout(30)
async def test_post_detail_reads_repost_wrapper_and_full_original_as_two_bounded_pages() -> None:
    fixtures = {
        REPOST_REF: "posts/latest/detail-repost.html",
        REPOST_ORIGINAL_REF: "posts/latest/detail-repost-original.html",
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PostFixtureBrowser(page, detail_fixtures=fixtures)
        reader = PostDetailPage(adapt_browser(fixture_browser))
        try:
            post = await reader.read(
                PostGetInput(
                    context_id="context-1",
                    request_id="detail-repost",
                    post_ref=REPOST_REF,
                )
            )
        finally:
            await browser.close()

    assert post.post_ref == REPOST_REF
    assert post.displayed_post_ref == REPOST_ORIGINAL_REF
    assert post.content_type is DetailPostContentType.REPOST
    assert post.author.name == "Riley Kapoor"
    assert post.text is not None and "worth sharing" in post.text
    assert post.hashtags == ("#resilience",)
    assert [mention.label for mention in post.mentions] == ["Alex Ray"]
    assert post.viewer_reaction is ReactionState.SUPPORT
    assert post.reshared_post is not None
    assert post.reshared_post.post_ref == REPOST_ORIGINAL_REF
    assert post.reshared_post.author.name == "Example Labs"
    assert post.reshared_post.author.verified is True
    assert post.reshared_post.text is not None
    assert "stop on ambiguous state" in post.reshared_post.text
    assert post.reshared_post.content_type is DetailPostContentType.LINK
    assert post.reshared_post.attachments[0].label == "The Bounded Recovery Guide"
    assert post.coverage.pages_visited == 2
    assert post.coverage.text_expanded is True
    assert post.coverage.reshared_post_present is True
    assert [post_reference_from_value(str(url)) for url in post.coverage.source_urls] == [
        REPOST_REF,
        REPOST_ORIGINAL_REF,
    ]
    assert fixture_browser.navigations == [
        f"https://www.linkedin.com/feed/update/urn:li:activity:{REPOST_REF.split(':')[1]}/",
        (f"https://www.linkedin.com/feed/update/urn:li:share:{REPOST_ORIGINAL_REF.split(':')[1]}/"),
    ]
    nested_evidence = [
        evidence for evidence in post.evidence if evidence.field.startswith("reshared_post.")
    ]
    assert nested_evidence
    assert {str(evidence.source_url) for evidence in nested_evidence} == {
        str(post.coverage.source_urls[1])
    }
    assert source_from_post(post).source_type.value == "linkedin_post"


@pytest.mark.timeout(30)
async def test_post_detail_classifies_every_current_visible_link_card_family() -> None:
    base = (FIXTURES / "posts/latest/detail-article.html").read_text(encoding="utf-8")
    variants = (
        (
            DetailPostContentType.ARTICLE,
            "https://www.linkedin.com/pulse/designing-recovery-avery-shah/",
        ),
        (
            DetailPostContentType.NEWSLETTER,
            "https://www.linkedin.com/newsletters/reliable-systems-123456789/",
        ),
        (
            DetailPostContentType.EVENT,
            "https://www.linkedin.com/events/reliabilityworkshop731234567890/",
        ),
        (
            DetailPostContentType.JOB,
            "https://www.linkedin.com/jobs/view/4100000001/",
        ),
        (DetailPostContentType.LINK, "https://example.test/recovery-guide"),
    )
    original_url = "https://www.linkedin.com/pulse/designing-recovery-avery-shah/"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for expected_type, card_url in variants:
                page = await browser.new_page()
                reader = PostDetailPage(
                    adapt_browser(
                        StaticPostFixtureBrowser(
                            page,
                            base.replace(original_url, card_url),
                        )
                    )
                )
                try:
                    post = await reader.read(
                        PostGetInput(
                            context_id="context-1",
                            request_id=f"card-{expected_type.value}",
                            post_ref=ARTICLE_POST_REF,
                        )
                    )
                finally:
                    await page.close()
                assert post.content_type is expected_type
                assert len(post.attachments) == 1
                assert post.attachments[0].content_type is expected_type
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_post_detail_preserves_a_single_page_activity_alias_without_inventing_repost() -> (
    None
):
    alias_ref = "share:7312345678901234599"
    html = (
        (FIXTURES / "posts/latest/detail-image.html")
        .read_text(encoding="utf-8")
        .replace(
            ("https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"),
            f"https://www.linkedin.com/feed/update/urn:li:share:{alias_ref.split(':')[1]}/",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostDetailPage(adapt_browser(StaticPostFixtureBrowser(page, html)))
        try:
            post = await reader.read(
                PostGetInput(
                    context_id="context-1",
                    request_id="single-page-alias",
                    post_ref=POST_REF,
                )
            )
        finally:
            await browser.close()

    assert post.post_ref == POST_REF
    assert post.displayed_post_ref == alias_ref
    assert post.content_type is DetailPostContentType.IMAGE
    assert post.reshared_post is None
    assert post.coverage.pages_visited == 1


@pytest.mark.timeout(20)
async def test_post_detail_accepts_role_article_with_legacy_visible_body() -> None:
    alias_ref = "share:7312345678901234599"
    html = (
        (FIXTURES / "posts/latest/detail-image.html")
        .read_text(encoding="utf-8")
        .replace(
            '<div role="listitem">',
            f'<div role="article" data-urn="urn:li:{alias_ref}">',
            1,
        )
        .replace(
            'data-testid="expandable-text-box"',
            'class="feed-shared-update-v2__description"',
            1,
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostDetailPage(adapt_browser(StaticPostFixtureBrowser(page, html)))
        try:
            post = await reader.read(
                PostGetInput(
                    context_id="context-1",
                    request_id="role-article-legacy-body",
                    post_ref=POST_REF,
                )
            )
        finally:
            await browser.close()

    assert post.post_ref == POST_REF
    assert post.displayed_post_ref == alias_ref
    assert post.text is not None and "recovery checks" in post.text
    assert post.content_type is DetailPostContentType.IMAGE


@pytest.mark.timeout(20)
async def test_comments_open_and_parse_modern_stable_ids_and_nested_replies() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = StaticPostFixtureBrowser(
            page,
            (FIXTURES / "posts/latest/comments.html").read_text(encoding="utf-8"),
        )
        reader = PostCommentsPage(
            adapt_browser(fixture_browser),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, captured_text, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="modern-comments",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert len(threads) == 1
    assert threads[0].comment.comment_ref == ("comment:activity:7312345678901234567:201")
    assert threads[0].comment.text == "Modern visible comment body."
    assert len(threads[0].replies) == 1
    assert threads[0].replies[0].comment_ref == ("comment:activity:7312345678901234567:202")
    assert threads[0].replies[0].parent_comment_ref == threads[0].comment.comment_ref
    assert threads[0].replies[0].text == "Modern nested reply."
    assert coverage.top_level_visible == 1
    assert coverage.replies_visible == 1
    assert "Modern visible comment body." in captured_text
    assert "Modern nested reply." in captured_text


@pytest.mark.timeout(20)
async def test_comments_parse_current_article_data_id_container() -> None:
    html = """
    <!doctype html>
    <html lang="en"><body><main>
      <div role="article" data-urn="urn:li:activity:7312345678901234567">
        <a href="/in/jane-doe/">Jane Doe</a>
        <p data-post-text>Current discussion fixture.</p>
        <button
          type="button"
          aria-label="Open control menu for post by Jane Doe"
        ></button>
        <button type="button" aria-label="Comment">1 comment</button>
        <article data-id="urn:li:comment:(activity:7312345678901234567,401)">
          <a href="/in/current-commenter/">
            Current Commenter
            <span>Platform Engineer</span>
          </a>
          <time>5m</time>
          <button
            type="button"
            aria-label="Open options for Current Commenter's comment"
          ></button>
          <p>Current visible comment body.</p>
          <button type="button" aria-label="React Like to Current Commenter's comment">
            Like
          </button>
          <button type="button" aria-label="Reply to Current Commenter's comment">
            Reply
          </button>
        </article>
      </div>
    </main></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostCommentsPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, _, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="current-data-id-comment",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert len(threads) == 1
    assert threads[0].comment.comment_ref == ("comment:activity:7312345678901234567:401")
    assert threads[0].comment.author.profile_slug == "current-commenter"
    assert threads[0].comment.text == "Current visible comment body."
    assert coverage.top_level_visible == 1
    assert coverage.top_level_returned == 1


@pytest.mark.timeout(20)
async def test_comments_bind_current_flattened_replies_to_nearest_root() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = StaticPostFixtureBrowser(
            page,
            (FIXTURES / "posts/latest/comments-flat-threads.html").read_text(encoding="utf-8"),
        )
        reader = PostCommentsPage(
            adapt_browser(fixture_browser),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, _, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="current-flat-comments",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert [thread.comment.comment_ref for thread in threads] == [
        "comment:activity:7312345678901234567:301",
        "comment:activity:7312345678901234567:303",
    ]
    assert [[reply.comment_ref for reply in thread.replies] for thread in threads] == [
        ["comment:activity:7312345678901234567:302"],
        ["comment:activity:7312345678901234567:304"],
    ]
    assert threads[0].comment.author.name == "Alex Ray"
    assert threads[0].comment.author.headline == "Principal Engineer"
    assert coverage.top_level_visible == 2
    assert coverage.replies_visible == 2


@pytest.mark.timeout(20)
async def test_comments_wait_for_discussion_after_async_sort_rerender() -> None:
    html = (
        (FIXTURES / "posts/latest/comments.html")
        .read_text(encoding="utf-8")
        .replace(
            '<section id="discussion" aria-label="Comments" hidden>',
            """
      <section id="discussion" aria-label="Comments" hidden>
        <button id="comment-sort" type="button">Most relevant</button>
        <div id="sort-options" role="listbox" hidden>
          <button id="most-recent" role="option" type="button">Most recent</button>
        </div>
""",
        )
        .replace(
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
""",
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
      document.querySelector("#comment-sort").addEventListener("click", () => {
        document.querySelector("#sort-options").hidden = false;
      });
      document.querySelector("#most-recent").addEventListener("click", () => {
        document.querySelector("#comment-sort").textContent = "Most recent";
        document.querySelector("#sort-options").hidden = true;
        const discussion = document.querySelector("#discussion");
        discussion.hidden = true;
        setTimeout(() => {
          discussion.hidden = false;
        }, 600);
      });
""",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = StaticPostFixtureBrowser(page, html)
        reader = PostCommentsPage(
            adapt_browser(fixture_browser),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, _, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="async-sort-comments",
                    post_ref=POST_REF,
                    sort_by=CommentSort.MOST_RECENT,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert len(threads) == 1
    assert threads[0].comment.text == "Modern visible comment body."
    assert coverage.sort_by is CommentSort.MOST_RECENT
    assert coverage.top_level_visible == 1


@pytest.mark.timeout(20)
async def test_comments_wait_for_async_load_more_render() -> None:
    html = (
        (FIXTURES / "posts/latest/comments.html")
        .read_text(encoding="utf-8")
        .replace(
            """
          </section>
        </div>
      </section>
    </main>
""",
            """
          </section>
        </div>
        <button id="load-more-comments" type="button">Load more comments</button>
        <template id="late-comment">
          <div
            id="replaceableComment_urn:li:comment:(urn:li:activity:7312345678901234567,203)"
          >
            <a href="/in/late-commenter-/">Late Commenter</a>
            <p><span>4h</span></p>
            <button
              type="button"
              aria-label="View more options for Late Commenter's comment."
            ></button>
            <div><p><span>Late-rendered top-level comment.</span></p></div>
            <button type="button" aria-label="Open reactions menu"></button>
            <button type="button" aria-label="Reply"></button>
          </div>
        </template>
      </section>
    </main>
""",
        )
        .replace(
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
""",
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
      document.querySelector("#load-more-comments").addEventListener("click", () => {
        setTimeout(() => {
          document.querySelector("#discussion").append(
            document.querySelector("#late-comment").content.cloneNode(true)
          );
          document.querySelector("#load-more-comments").remove();
        }, 600);
      });
""",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostCommentsPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, captured_text, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="async-load-more-comments",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert [thread.comment.comment_ref for thread in threads] == [
        "comment:activity:7312345678901234567:201",
        "comment:activity:7312345678901234567:203",
    ]
    assert coverage.expansion_rounds == 1
    assert "Late-rendered top-level comment." in captured_text


@pytest.mark.timeout(20)
async def test_comments_expand_current_see_previous_replies_control() -> None:
    html = (
        (FIXTURES / "posts/latest/comments.html")
        .read_text(encoding="utf-8")
        .replace(
            '<section aria-label="Replies">',
            (
                '<div id="see-previous-replies" role="button" tabindex="0">'
                "See previous replies</div>"
                '<section id="older-replies" aria-label="Replies" hidden>'
            ),
        )
        .replace(
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
""",
            """
      document.querySelector("#open-comments").addEventListener("click", () => {
        document.querySelector("#discussion").hidden = false;
      });
      document.querySelector("#see-previous-replies").addEventListener("click", () => {
        document.querySelector("#older-replies").hidden = false;
        document.querySelector("#see-previous-replies").remove();
      });
""",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostCommentsPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_expansion_rounds=2,
        )
        try:
            threads, coverage, _, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="see-previous-replies",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert coverage.expansion_rounds == 1
    assert coverage.replies_visible == 1
    assert len(threads[0].replies) == 1


@pytest.mark.timeout(20)
async def test_comments_preserve_native_ugc_discussion_alias_for_activity_url() -> None:
    native_post_ref = "ugc-post:7999999999999999998"
    html = (
        (FIXTURES / "posts/latest/comments.html")
        .read_text(encoding="utf-8")
        .replace(
            "urn:li:comment:(urn:li:activity:7312345678901234567,",
            "urn:li:comment:(urn:li:ugcPost:7999999999999999998,",
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = StaticPostFixtureBrowser(page, html)
        reader = PostCommentsPage(
            adapt_browser(fixture_browser),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, captured_text, source_url = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="aliased-comments",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert coverage.post_ref == POST_REF
    assert coverage.discussion_post_ref == native_post_ref
    assert threads[0].comment.post_ref == native_post_ref
    assert threads[0].comment.comment_ref == ("comment:ugc-post:7999999999999999998:201")
    assert threads[0].replies[0].post_ref == native_post_ref
    assert threads[0].replies[0].parent_comment_ref == threads[0].comment.comment_ref
    assert (
        source_from_post_comments(
            source_url=source_url,
            captured_text=captured_text,
            threads=threads,
            coverage=coverage,
        ).source_type.value
        == "linkedin_post_comments"
    )


@pytest.mark.timeout(20)
async def test_comments_accept_single_rendered_post_alias_for_requested_activity() -> None:
    displayed_post_ref = "share:7999999999999999997"
    html = (
        (FIXTURES / "posts/latest/comments.html")
        .read_text(encoding="utf-8")
        .replace(
            'data-post-urn="urn:li:activity:7312345678901234567"',
            'data-post-urn="urn:li:share:7999999999999999997"',
        )
        .replace(
            '<button id="open-comments"',
            (
                '<button aria-label="Open control menu for post by Jane Doe"></button>'
                '\n        <button id="open-comments"'
            ),
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = PostCommentsPage(
            adapt_browser(StaticPostFixtureBrowser(page, html)),
            max_expansion_rounds=1,
        )
        try:
            threads, coverage, _, _ = await reader.collect(
                PostCommentsListInput(
                    context_id="context-1",
                    request_id="rendered-post-alias-comments",
                    post_ref=POST_REF,
                    page_size=10,
                    max_replies_per_comment=10,
                )
            )
        finally:
            await browser.close()

    assert displayed_post_ref != coverage.post_ref
    assert coverage.post_ref == POST_REF
    assert coverage.discussion_post_ref == POST_REF
    assert threads[0].comment.post_ref == POST_REF


@pytest.mark.timeout(20)
async def test_post_detail_fails_closed_without_exact_requested_reference() -> None:
    html = (
        (FIXTURES / "posts/latest/detail-image.html")
        .read_text(encoding="utf-8")
        .replace(
            'aria-label="Open control menu for post by Jane Doe"',
            'aria-label="Post options for Jane Doe"',
        )
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = StaticPostFixtureBrowser(page, html)
        reader = PostDetailPage(adapt_browser(fixture_browser))
        try:
            with pytest.raises(ParserDriftError, match="exact visible requested post"):
                await reader.read(
                    PostGetInput(
                        context_id="context-1",
                        request_id="wrong-post-reference",
                        post_ref=POST_REF,
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(30)
async def test_post_detail_fails_closed_on_current_ui_drift_and_safety_bounds() -> None:
    image = (FIXTURES / "posts/latest/detail-image.html").read_text(encoding="utf-8")
    poll = (FIXTURES / "posts/latest/detail-poll-closed.html").read_text(encoding="utf-8")
    repost = (FIXTURES / "posts/latest/detail-repost.html").read_text(encoding="utf-8")
    cases = (
        (
            image.replace(
                '<a href="/in/jane-doe/">',
                ('<a href="/in/jane-impostor/">Jane Doe</a><a href="/in/jane-doe/">'),
                1,
            ),
            POST_REF,
            "ambiguous visible author identity",
        ),
        (
            image.replace("event.currentTarget.remove();", "void event;"),
            POST_REF,
            "remained visibly truncated",
        ),
        (
            poll.replace('class="poll-option"', 'class="poll-option" hidden'),
            CLOSED_POLL_POST_REF,
            "without complete visible poll options",
        ),
        (
            repost.replace(
                '<section aria-label="Reposted content">',
                (
                    '<div data-testid="expandable-text-box">'
                    "Unexpected third post body</div>"
                    '<section aria-label="Reposted content">'
                ),
            ),
            REPOST_REF,
            "more than one bounded repost layer",
        ),
        (
            (
                "<html><body><main>"
                + "".join(
                    (f'<button aria-label="Open control menu for post by Author {index}"></button>')
                    for index in range(21)
                )
                + "</main></body></html>"
            ),
            POST_REF,
            "bounded post-menu limit",
        ),
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for index, (html, post_ref, error_text) in enumerate(cases):
                page = await browser.new_page()
                reader = PostDetailPage(adapt_browser(StaticPostFixtureBrowser(page, html)))
                try:
                    with pytest.raises(ParserDriftError, match=error_text):
                        await reader.read(
                            PostGetInput(
                                context_id="context-1",
                                request_id=f"post-drift-{index}",
                                post_ref=post_ref,
                            )
                        )
                finally:
                    await page.close()
        finally:
            await browser.close()
