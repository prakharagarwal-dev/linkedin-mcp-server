"""Visible post mechanics shared by comment and reaction pages."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.posts.surface import (
    post_author_from_region,
    region_for_post,
)
from linkedin_mcp.ui import LinkedInLocator as Locator
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.urls import profile_slug_from_url


@dataclass(frozen=True, slots=True)
class VisiblePostTarget:
    region: Locator
    actor_slug: str
    actor_name: str
    content_author_name: str
    content_author_url: HttpUrl | None


class PostEngagementSurface:
    """Shared visible-surface mechanics for PostEngagementSurface."""

    def __init__(self, playwright: LinkedInPlaywright) -> None:
        self._playwright = playwright

    async def _resolve_target(
        self,
        page: Page,
        post_ref: str,
    ) -> VisiblePostTarget:
        post_region = await region_for_post(page, post_ref)
        author = await post_author_from_region(post_region)
        actor_slug, actor_name = await self._active_actor(page)
        return VisiblePostTarget(
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
