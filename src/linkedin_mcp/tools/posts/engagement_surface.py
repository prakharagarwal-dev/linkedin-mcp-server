"""Visible post mechanics shared by comment and reaction pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
)
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.urls import (
    canonical_post_url,
    canonical_profile_url,
    profile_slug_from_url,
)
from linkedin_mcp.tools.posts.surface import (
    post_author_from_region,
    region_for_post,
)

_COMMENT_ATTACHMENT_SELECTOR = (
    "[data-comment-attachment], [data-test-comment-attachment], "
    '[class*="comments-comment-item__comment-image"], '
    '[class*="comments-comment-item__gif"], '
    '[class*="comments-comment-item__media"]'
)


@dataclass(frozen=True, slots=True)
class _VisibleTarget:
    region: Locator
    actor_slug: str
    actor_name: str
    content_author_name: str
    content_author_url: HttpUrl | None


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        value = (await locator.first.inner_text()).strip()
        if value:
            attachments = page.locator(_COMMENT_ATTACHMENT_SELECTOR)
            accessible: list[str] = []
            for index in range(min(await attachments.count(), 100)):
                attachment = attachments.nth(index)
                if not await attachment.is_visible():
                    continue
                media = attachment.locator("img, video, a").first
                for candidate in (
                    await attachment.get_attribute("aria-label"),
                    (await media.get_attribute("aria-label") if await media.count() else None),
                    await media.get_attribute("alt") if await media.count() else None,
                ):
                    if candidate and candidate not in value and candidate not in accessible:
                        accessible.append(candidate)
            if accessible:
                value = f"{value}\n\n--- accessible comment attachment evidence ---\n" + "\n".join(
                    accessible
                )
            return value
    raise ParserDriftError("LinkedIn returned no visible engagement text.")


class PostEngagementSurface:
    """Shared visible-surface mechanics for PostEngagementSurface."""

    def __init__(self, browser: BrowserManager, assets: LocalAssetStore) -> None:
        self._browser = browser
        self._assets = assets

    async def _resolve_target(
        self,
        page: Page,
        post_ref: str,
    ) -> _VisibleTarget:
        post_region = await region_for_post(page, post_ref)
        author = await post_author_from_region(post_region)
        actor_slug, actor_name = await self._active_actor(page)
        return _VisibleTarget(
            region=post_region,
            actor_slug=actor_slug,
            actor_name=actor_name,
            content_author_name=author.name,
            content_author_url=author.author_url,
        )

    @staticmethod
    async def _active_actor(page: Page) -> tuple[str, str]:
        rail_slugs: set[str] = set()
        named_candidates: list[tuple[int, str, str]] = []
        for attempt in range(21):
            explicit_candidates = page.locator(
                "a[data-active-member][href*='/in/'], "
                "[data-active-member] a[href*='/in/'], "
                "nav a[aria-label*='profile' i][href*='/in/']"
            )
            values: list[tuple[str, str]] = []
            for index in range(min(await explicit_candidates.count(), 20)):
                candidate = explicit_candidates.nth(index)
                if not await candidate.is_visible():
                    continue
                href = await candidate.get_attribute("href")
                slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
                name = (await candidate.inner_text()).strip().splitlines()
                if slug and name and name[0].strip():
                    values.append((slug, name[0].strip()))
            unique = list(dict.fromkeys(values))
            if len(unique) == 1:
                return unique[0]
            if unique:
                raise ParserDriftError("LinkedIn has no unique visible active member identity.")

            # The current post-detail layout exposes the signed-in member's
            # profile card in a complementary rail after the post itself. Bind
            # only when every visible profile link in that rail resolves to one
            # stable member slug and a visible display name.
            rail_candidates = page.locator("aside a[href*='/in/']")
            rail_slugs = set()
            named_candidates = []
            for index in range(min(await rail_candidates.count(), 50)):
                candidate = rail_candidates.nth(index)
                if not await candidate.is_visible():
                    continue
                href = await candidate.get_attribute("href")
                slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
                if slug is None:
                    continue
                rail_slugs.add(slug)
                text = (await candidate.inner_text()).strip()
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if lines and any(character.isalpha() for character in lines[0]):
                    named_candidates.append((len(text), slug, lines[0]))
            if len(rail_slugs) == 1:
                actor_slug = next(iter(rail_slugs))
                names = [candidate for candidate in named_candidates if candidate[1] == actor_slug]
                if names:
                    _, _, actor_name = max(names, key=lambda candidate: candidate[0])
                    return actor_slug, actor_name
            if attempt < 20:
                await page.wait_for_timeout(250)

        if len(rail_slugs) == 1 and not named_candidates:
            raise ParserDriftError("LinkedIn has no visible active member display name.")
        raise ParserDriftError("LinkedIn has no unique visible active member identity.")

    @staticmethod
    def _action_target(
        target: _VisibleTarget,
        post_ref: str,
    ) -> ActionTarget:
        actor_url = HttpUrl(canonical_profile_url(target.actor_slug))
        return ActionTarget(
            profile_slug=target.actor_slug,
            profile_url=actor_url,
            display_name=target.actor_name,
            actor_profile_slug=target.actor_slug,
            actor_profile_url=actor_url,
            actor_display_name=target.actor_name,
            post_ref=post_ref,
            post_url=HttpUrl(canonical_post_url(post_ref)),
            content_author_name=target.content_author_name,
            content_author_url=target.content_author_url,
        )

    @staticmethod
    def _matches_inspected_target(
        requested: ActionTarget,
        current: _VisibleTarget,
    ) -> bool:
        return (
            (requested.actor_profile_slug or requested.profile_slug) == current.actor_slug
            and (requested.actor_display_name or requested.display_name).casefold()
            == current.actor_name.casefold()
            and requested.content_author_name is not None
            and requested.content_author_name.casefold() == current.content_author_name.casefold()
            and (
                requested.content_author_url is None
                or (
                    current.content_author_url is not None
                    and str(requested.content_author_url) == str(current.content_author_url)
                )
            )
        )

    @staticmethod
    async def _result(
        page: Page,
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
    ) -> ActionPageResult:
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=HttpUrl(page.url),
            captured_text=await _visible_text(page),
            captured_at=datetime.now(UTC),
        )
