"""Visible LinkedIn page implementation for `linkedin_mcp.tools.people.get.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urljoin, urlsplit

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.people.get.models import (
    PROFILE_SLUG_SEGMENT_PATTERN,
    PeopleGetInput,
    PersonConnectionDegree,
    PersonEducation,
    PersonExperience,
    PersonProfileCoverage,
    PersonProfileEvidence,
    PersonProfileLink,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonProfileSection,
    PersonProfileSectionEntry,
    PersonProfileSectionSelector,
)
from linkedin_mcp.tools.people.surface import (
    ACTION_LINES,
    CONNECTION_COUNT_PATTERN,
    CONNECTION_DEGREE_PATTERN,
    FOLLOWER_COUNT_PATTERN,
    connection_degree,
    first_text,
    unique_lines,
)
from linkedin_mcp.ui import LinkedInLocator as Locator
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.urls import canonical_profile_url, profile_slug_from_url

_DATE_RANGE_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}\b|\bPresent\b|\b(?:\d+\s+)?(?:mos?|yrs?)\b",
    re.IGNORECASE,
)

_EMPLOYMENT_TYPE_LINES = frozenset(
    {
        "apprenticeship",
        "contract",
        "freelance",
        "full-time",
        "internship",
        "part-time",
        "seasonal",
        "self-employed",
        "temporary",
        "volunteer",
    }
)

_SKILL_ACTION_PATTERN = re.compile(
    r"^(?:endorse|remove endorsement for|unendorse)\s+(.+)$",
    re.IGNORECASE,
)

_PROFILE_DETAIL_PATH = re.compile(
    rf"^/in/(?P<slug>{PROFILE_SLUG_SEGMENT_PATTERN})/"
    r"details/(?P<section>[A-Za-z0-9_-]+)/?"
)

_DETAIL_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": ("experience",),
    "education": ("education",),
    "certifications": ("licenses & certifications", "certifications"),
    "projects": ("projects",),
    "volunteering-experiences": ("volunteering", "volunteer experience"),
    "skills": ("skills",),
    "interests": ("interests",),
    "featured": ("featured",),
    "courses": ("courses",),
    "honors": ("honors & awards", "honors"),
    "languages": ("languages",),
    "organizations": ("organizations",),
    "publications": ("publications",),
    "patents": ("patents",),
    "recommendations": ("recommendations",),
    "test-scores": ("test scores",),
}

_CANONICAL_DETAIL_SECTION_KEYS = {
    "certifications": "licenses-certifications",
    "honors": "honors-awards",
    "volunteering-experiences": "volunteering",
}

_CANONICAL_HEADING_SECTION_KEYS = {
    "volunteer-experience": "volunteering",
}

_AUXILIARY_PROFILE_SECTION_KEYS = frozenset(
    {
        "analytics",
        "explore-premium-profiles",
        "guidance",
        "more-profiles-for-you",
        "people-you-may-know",
        "profile-language",
        "public-profile-url",
        "resources",
        "suggested-for-you",
        "who-your-viewers-also-viewed",
        "you-might-like",
    }
)


def _section_key(heading: str, source_url: str) -> str:
    detail_match = _PROFILE_DETAIL_PATH.match(urlsplit(source_url).path)
    if detail_match:
        raw_key = detail_match.group("section").lower().replace("_", "-")
        return _CANONICAL_DETAIL_SECTION_KEYS.get(raw_key, raw_key)
    without_count = re.sub(r"\s*\([\d,]+\)\s*$", "", heading)
    normalized = re.sub(r"[^a-z0-9]+", "-", without_count.casefold()).strip("-")
    normalized = normalized[:100] or "other"
    return _CANONICAL_HEADING_SECTION_KEYS.get(normalized, normalized)


def _detail_section_key(url: str) -> str:
    match = _PROFILE_DETAIL_PATH.match(urlsplit(url).path)
    if match is None:
        raise ParserDriftError("LinkedIn profile detail link has an unsupported path.")
    raw_key = match.group("section").lower().replace("_", "-")
    return _CANONICAL_DETAIL_SECTION_KEYS.get(raw_key, raw_key)


def _detail_heading_matches(detail_key: str, heading: str) -> bool:
    normalized_heading = re.sub(
        r"\s+",
        " ",
        re.sub(r"\s*\([\d,]+\)\s*$", "", heading).strip().casefold(),
    )
    aliases = _DETAIL_SECTION_ALIASES.get(
        detail_key,
        (detail_key.replace("-", " "),),
    )
    return normalized_heading in aliases


async def _detail_section_from_visible_heading(
    main: Locator,
    source_url: str,
    detail_key: str,
) -> PersonProfileSection | None:
    values: list[PersonProfileSection] = []
    aliases = _DETAIL_SECTION_ALIASES.get(
        detail_key,
        (detail_key.replace("-", " "),),
    )
    for alias in aliases:
        candidates = main.get_by_text(
            re.compile(
                rf"^{re.escape(alias)}(?:\s*\([\d,]+\))?$",
                re.IGNORECASE,
            )
        )
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if not await candidate.is_visible():
                continue
            sections = candidate.locator("xpath=ancestor::section[1]")
            region = sections.first if await sections.count() else candidate.locator("..")
            visible_text = (await region.inner_text()).strip()
            if not visible_text:
                continue
            heading = (await candidate.inner_text()).strip()
            heading_lines = unique_lines(heading)
            values.append(
                PersonProfileSection(
                    key=_section_key(heading, source_url),
                    heading=heading_lines[0] if heading_lines else alias,
                    source_url=HttpUrl(source_url),
                    visible_text=visible_text,
                    entries=await _entries_for_section(
                        region,
                        _section_key(heading, source_url),
                    ),
                )
            )
    return (
        max(
            values,
            key=lambda section: (len(section.entries), len(section.visible_text)),
        )
        if values
        else None
    )


async def _entry_links(entry: Locator) -> tuple[PersonProfileLink, ...]:
    links: list[PersonProfileLink] = []
    locators = entry.locator("a[href]")
    for index in range(min(await locators.count(), 50)):
        link = locators.nth(index)
        href = await link.get_attribute("href")
        if not href:
            continue
        absolute_url = urljoin("https://www.linkedin.com", href)
        if urlsplit(absolute_url).scheme not in {"http", "https"}:
            continue
        aria_label = (await link.get_attribute("aria-label") or "").strip()
        visible_label = (await link.inner_text()).strip()
        label = aria_label or visible_label
        if len(label) > 1_000:
            label_lines = unique_lines(label)
            label = (label_lines[0] if label_lines else label)[:1_000].strip()
        if not label:
            continue
        item = PersonProfileLink(label=label, url=HttpUrl(absolute_url))
        if item not in links:
            links.append(item)
    return tuple(links)


async def _section_entries(section: Locator) -> tuple[PersonProfileSectionEntry, ...]:
    entries: list[PersonProfileSectionEntry] = []
    items = section.get_by_role("listitem")
    for index in range(min(await items.count(), 500)):
        item = items.nth(index)
        if not await item.is_visible() or await item.get_by_role("listitem").count():
            continue
        visible_text = (await item.inner_text()).strip()
        lines = unique_lines(visible_text)
        if not lines:
            continue
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=await _entry_links(item),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _current_collection_entries(
    section: Locator,
) -> tuple[PersonProfileSectionEntry, ...]:
    """Read current roleless profile-detail cards from their collection boundary."""

    entries: list[PersonProfileSectionEntry] = []
    items = section.locator(
        '[data-component-type="LazyColumn"] '
        "> [data-lazy-mount-id] "
        '> [componentkey^="entity-collection-item-"]'
    )
    for index in range(min(await items.count(), 500)):
        item = items.nth(index)
        if not await item.is_visible():
            continue
        visible_text = (await item.inner_text()).strip()
        lines = unique_lines(visible_text)
        if not lines:
            continue
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=await _entry_links(item),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _skill_entries(section: Locator) -> tuple[PersonProfileSectionEntry, ...]:
    """Bind current skill cards through their exact accessible action control."""

    entries: list[PersonProfileSectionEntry] = []
    seen_skills: set[str] = set()
    controls = section.get_by_role("button")
    for index in range(min(await controls.count(), 500)):
        control = controls.nth(index)
        if not await control.is_visible():
            continue
        accessible_name = (await control.get_attribute("aria-label") or "").strip()
        match = _SKILL_ACTION_PATTERN.fullmatch(accessible_name)
        if not match:
            continue
        skill_name = match.group(1).strip()
        if not skill_name or skill_name.casefold() in seen_skills:
            continue

        region = control.locator("xpath=..")
        for _ in range(6):
            visible_text = (await region.inner_text()).strip()
            lines = unique_lines(visible_text)
            matching_controls = region.get_by_role("button", name=accessible_name, exact=True)
            if (
                lines
                and lines[0].casefold() == skill_name.casefold()
                and await matching_controls.count() == 1
            ):
                action_lines = {
                    line.casefold()
                    for line in unique_lines(await matching_controls.first.inner_text())
                }
                metadata_lines = [
                    line
                    for line in lines[1:]
                    if line.casefold() not in action_lines
                    and line.casefold() != accessible_name.casefold()
                ]
                entries.append(
                    PersonProfileSectionEntry(
                        title=skill_name,
                        subtitle=metadata_lines[0] if metadata_lines else None,
                        visible_text=visible_text,
                        links=await _entry_links(region),
                    )
                )
                seen_skills.add(skill_name.casefold())
                break
            region = region.locator("xpath=..")
    return tuple(entries)


async def _linked_section_entries(
    section: Locator,
    link_fragment: str,
) -> tuple[PersonProfileSectionEntry, ...]:
    raw_entries = await section.locator(f'a[href*="{link_fragment}"]').evaluate_all(
        """
        (elements, fragment) => elements.slice(0, 500).flatMap(link => {
          let region = link.parentElement;
          for (let index = 0; region && index < 9; index += 1) {
            const visibleText = region.innerText?.trim() ?? "";
            const lines = visibleText.split("\\n").map(value => value.trim()).filter(Boolean);
            const matchingLinks =
              region.querySelectorAll(`a[href*="${fragment}"]`).length;
            if (lines.length >= 2 && matchingLinks === 1) {
              return [{
                visible_text: visibleText,
                links: Array.from(region.querySelectorAll("a[href]"))
                  .slice(0, 50)
                  .map(item => ({
                    href: item.getAttribute("href") ?? "",
                    text: item.innerText?.trim() ?? "",
                    aria_label: item.getAttribute("aria-label")
                  }))
              }];
            }
            region = region.parentElement;
          }
          return [];
        })
        """,
        link_fragment,
    )
    entries: list[PersonProfileSectionEntry] = []
    for raw_entry in cast(list[object], raw_entries):
        if not isinstance(raw_entry, dict):
            continue
        entry_value = cast(dict[str, object], raw_entry)
        visible_text = entry_value.get("visible_text")
        raw_links = entry_value.get("links")
        if not isinstance(visible_text, str) or not visible_text or not isinstance(raw_links, list):
            continue
        lines = unique_lines(visible_text)
        if not lines:
            continue
        links: list[PersonProfileLink] = []
        for raw_link in cast(list[object], raw_links):
            if not isinstance(raw_link, dict):
                continue
            link_value = cast(dict[str, object], raw_link)
            href = link_value.get("href")
            text = link_value.get("text")
            aria_label = link_value.get("aria_label")
            if (
                not isinstance(href, str)
                or not href
                or not isinstance(text, str)
                or not (isinstance(aria_label, str) or aria_label is None)
            ):
                continue
            absolute_url = urljoin("https://www.linkedin.com", href)
            if urlsplit(absolute_url).scheme not in {"http", "https"}:
                continue
            label = (aria_label or text).strip()
            if len(label) > 1_000:
                label_lines = unique_lines(label)
                label = (label_lines[0] if label_lines else label)[:1_000].strip()
            if label:
                item = PersonProfileLink(label=label, url=HttpUrl(absolute_url))
                if item not in links:
                    links.append(item)
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=tuple(links),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _entries_for_section(
    section: Locator,
    section_key: str,
) -> tuple[PersonProfileSectionEntry, ...]:
    if section_key == "skills":
        current_entries = await _skill_entries(section)
        if current_entries:
            return current_entries
    if section_key not in {"education", "experience", "interests", "skills"}:
        current_entries = await _current_collection_entries(section)
        if current_entries:
            return current_entries
    entries = await _section_entries(section)
    if entries:
        return entries
    link_fragment = {
        "experience": "/company/",
        "education": "/school/",
        "interests": "/company/",
    }.get(section_key)
    linked_entries = await _linked_section_entries(section, link_fragment) if link_fragment else ()
    if section_key != "interests":
        return linked_entries
    return tuple(
        entry.model_copy(
            update={
                "title": (
                    re.sub(r",\s*Company$", "", entry.title, flags=re.IGNORECASE)
                    if entry.title
                    else entry.title
                ),
                "subtitle": _find_line(unique_lines(entry.visible_text), FOLLOWER_COUNT_PATTERN)
                or entry.subtitle,
            }
        )
        for entry in linked_entries
    )


async def _extract_sections(
    main: Locator,
    source_url: str,
    *,
    profile_name: str,
) -> tuple[PersonProfileSection, ...]:
    results: list[PersonProfileSection] = []
    sections = main.locator("section")
    for index in range(min(await sections.count(), 100)):
        section = sections.nth(index)
        if not await section.is_visible():
            continue
        headings = section.get_by_role("heading")
        heading = await first_text(headings)
        if not heading:
            continue
        heading_lines = unique_lines(heading)
        heading = heading_lines[0] if heading_lines else heading
        if heading == profile_name:
            continue
        visible_text = (await section.inner_text()).strip()
        if not visible_text or visible_text == heading:
            continue
        section_key = _section_key(heading, source_url)
        if section_key in _AUXILIARY_PROFILE_SECTION_KEYS:
            continue
        results.append(
            PersonProfileSection(
                key=section_key,
                heading=heading,
                source_url=HttpUrl(source_url),
                visible_text=visible_text,
                entries=await _entries_for_section(section, section_key),
            )
        )
    detail_match = _PROFILE_DETAIL_PATH.match(urlsplit(source_url).path)
    if not results and detail_match:
        page_heading = await first_text(main.get_by_role("heading"))
        page_text = (await main.inner_text()).strip()
        if page_heading and page_text and page_text != page_heading:
            results.append(
                PersonProfileSection(
                    key=_section_key(page_heading, source_url),
                    heading=unique_lines(page_heading)[0],
                    source_url=HttpUrl(source_url),
                    visible_text=page_text,
                    entries=await _entries_for_section(
                        main,
                        _section_key(page_heading, source_url),
                    ),
                )
            )

    if detail_match:
        detail_key = detail_match.group("section").lower().replace("_", "-")
        matching = [
            section for section in results if _detail_heading_matches(detail_key, section.heading)
        ]
        if not matching:
            fallback = await _detail_section_from_visible_heading(
                main,
                source_url,
                detail_key,
            )
            if fallback is not None:
                return (fallback,)
            raise ParserDriftError(
                f"LinkedIn profile detail {detail_key!r} had no matching visible section."
            )
        return (
            max(
                matching,
                key=lambda section: (len(section.entries), len(section.visible_text)),
            ),
        )
    return tuple(results)


def _section_body(section: PersonProfileSection) -> str | None:
    value = section.visible_text.strip()
    heading_index = value.casefold().find(section.heading.casefold())
    if heading_index == 0:
        value = value[len(section.heading) :].strip()
    value = re.split(
        r"\n\s*(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)\s*more\s*(?:\n|$)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.split(
        r"\n\s*top skills\s*(?:\n|$)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.sub(
        r"\n(?:see more|show all|show less)(?:\s+[^\n]+)?\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value or None


def _find_line(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    return next((line for line in lines if pattern.search(line)), None)


def _first_pattern_text(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0).strip()
    return None


def _looks_like_experience_location(value: str) -> bool:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        return False
    if normalized.startswith(("-", "*", "\N{BULLET}")):
        return False
    if normalized.casefold().startswith(("core technologies:", "skills:")):
        return False
    lowered = normalized.casefold()
    if re.search(r"\bskills?\b", lowered):
        return False
    return (
        lowered in {"remote", "hybrid", "on-site", "onsite"}
        or "," in normalized
        or lowered.endswith(" area")
    )


def _parse_experiences(
    sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonExperience, ...]:
    values: list[PersonExperience] = []
    for section in sections:
        if section.heading.casefold() != "experience" and section.key != "experience":
            continue
        for entry in section.entries:
            lines = unique_lines(entry.visible_text)
            if not lines:
                continue
            skill_association_lines = {
                line
                for link in entry.links
                if "skill-associations-details" in urlsplit(str(link.url)).path
                for line in unique_lines(link.label)
            }
            date_range = _find_line(lines, _DATE_RANGE_PATTERN)
            date_index = lines.index(date_range) if date_range in lines else -1
            title = lines[0]
            organization_line = lines[1] if len(lines) > 1 and lines[1] != date_range else None
            organization: str | None = None
            employment_type: str | None = None
            if organization_line:
                if organization_line.casefold() in _EMPLOYMENT_TYPE_LINES:
                    employment_type = organization_line
                else:
                    organization_parts = [part.strip() for part in organization_line.split("·")]
                    organization = organization_parts[0] or None
                    employment_type = organization_parts[1] if len(organization_parts) > 1 else None
            date_parts = [part.strip() for part in date_range.split("·")] if date_range else []
            location_candidate = (
                lines[date_index + 1] if date_index >= 0 and date_index + 1 < len(lines) else None
            )
            location = (
                location_candidate
                if location_candidate
                and location_candidate not in skill_association_lines
                and _looks_like_experience_location(location_candidate)
                else None
            )
            description_start = date_index + 2 if location else date_index + 1
            description_lines = lines[description_start:] if description_start > 0 else lines[2:]
            cleaned_description_lines: list[str] = []
            for line in description_lines:
                if re.fullmatch(
                    r"(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)\s*more",
                    line,
                    flags=re.IGNORECASE,
                ):
                    break
                if line not in skill_association_lines:
                    cleaned_description_lines.append(line)
            organization_url = next(
                (link.url for link in entry.links if "/company/" in urlsplit(str(link.url)).path),
                None,
            )
            values.append(
                PersonExperience(
                    title=title,
                    organization=organization,
                    organization_url=organization_url,
                    employment_type=employment_type,
                    date_range=date_parts[0] if date_parts else date_range,
                    duration=date_parts[1] if len(date_parts) > 1 else None,
                    location=location,
                    description="\n".join(cleaned_description_lines).strip() or None,
                    is_current=("present" in date_range.casefold() if date_range else None),
                    source_url=section.source_url,
                    visible_text=entry.visible_text,
                )
            )
    return tuple(values)


def _parse_education(
    sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonEducation, ...]:
    values: list[PersonEducation] = []
    for section in sections:
        if section.heading.casefold() != "education" and section.key != "education":
            continue
        for entry in section.entries:
            lines = unique_lines(entry.visible_text)
            if not lines:
                continue
            date_range = _find_line(lines, _DATE_RANGE_PATTERN)
            date_index = lines.index(date_range) if date_range in lines else -1
            degree_line = lines[1] if len(lines) > 1 and lines[1] != date_range else None
            degree_parts = (
                [part.strip() for part in degree_line.split(",", maxsplit=1)] if degree_line else []
            )
            description_lines = lines[date_index + 1 :] if date_index >= 0 else lines[2:]
            school_url = next(
                (link.url for link in entry.links if "/school/" in urlsplit(str(link.url)).path),
                None,
            )
            values.append(
                PersonEducation(
                    school=lines[0],
                    school_url=school_url,
                    degree=degree_parts[0] if degree_parts else None,
                    field_of_study=degree_parts[1] if len(degree_parts) > 1 else None,
                    date_range=date_range,
                    description="\n".join(description_lines).strip() or None,
                    source_url=section.source_url,
                    visible_text=entry.visible_text,
                )
            )
    return tuple(values)


async def _expand_and_scroll(page: Page) -> None:
    main = page.locator("main")
    source_path = urlsplit(page.url).path.rstrip("/")
    for scroll_index in range(8):
        try:
            await main.wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                "LinkedIn member profile became unavailable during bounded scrolling "
                f"at step {scroll_index + 1}."
            ) from error
        await main.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        await page.keyboard.press("End")
        await page.wait_for_timeout(200)
        if urlsplit(page.url).path.rstrip("/") != source_path:
            raise ParserDriftError("LinkedIn member profile navigated away during scrolling.")
    buttons = main.get_by_role(
        "button",
        name=re.compile(r"^(?:see more|show more)", re.IGNORECASE),
    )
    for index in range(min(await buttons.count(), 100)):
        button = buttons.nth(index)
        try:
            if not await button.is_visible():
                continue
            source_url = page.url
            await button.click(timeout=1_000)
            if page.url != source_url:
                raise ParserDriftError(
                    "A profile content-expansion control unexpectedly navigated away."
                )
        except PlaywrightTimeoutError:
            continue
    await main.evaluate("element => { element.scrollTop = 0; }")
    await page.keyboard.press("Home")


async def _visible_page_text(page: Page) -> str:
    text = await first_text(page.locator("main"))
    if text:
        return text
    text = await first_text(page.locator("body"))
    if not text:
        raise ParserDriftError("LinkedIn member profile returned no visible text.")
    return text


async def _profile_detail_urls(
    main: Locator,
    profile_slug: str,
) -> tuple[str, ...]:
    urls: list[str] = []
    links = main.locator('a[href*="/details/"]')
    for index in range(min(await links.count(), 100)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        if not href:
            continue
        label = " ".join(
            (
                (await link.inner_text()).strip(),
                (await link.get_attribute("aria-label") or "").strip(),
            )
        ).strip()
        if not re.search(r"\b(?:show|see)\s+all\b", label, re.IGNORECASE):
            continue
        url = urljoin("https://www.linkedin.com", href)
        match = _PROFILE_DETAIL_PATH.match(urlsplit(url).path)
        if not match or match.group("slug") != profile_slug:
            continue
        clean_url = f"https://www.linkedin.com{urlsplit(url).path}"
        if _detail_section_key(clean_url) in _AUXILIARY_PROFILE_SECTION_KEYS:
            continue
        if clean_url not in urls:
            urls.append(clean_url)
    return tuple(urls)


async def _top_card(main: Locator) -> tuple[Locator, str, str]:
    headings = main.get_by_role("heading", level=1)
    name = await first_text(headings)
    if not name:
        page = main.page
        title = await page.title()
        candidate = re.split(r"\s*[|·]\s*LinkedIn", title, maxsplit=1)[0].strip()
        main_text = (await main.inner_text()).strip()
        if (
            not candidate
            or len(candidate) > 500
            or candidate not in {line.strip() for line in main_text.splitlines()}
        ):
            raise ParserDriftError("LinkedIn member profile has no exact visible member name.")
        candidate_headings = main.get_by_role(
            "heading",
            name=re.compile(rf"^{re.escape(candidate)}$"),
        )
        visible_headings: list[Locator] = []
        for index in range(await candidate_headings.count()):
            heading = candidate_headings.nth(index)
            if await heading.is_visible():
                visible_headings.append(heading)
        if len(visible_headings) != 1:
            raise ParserDriftError("LinkedIn member profile has no unique visible member name.")
        name = candidate
        name_heading = visible_headings[0]
    else:
        name = unique_lines(name)[0]
        name_heading = headings.first
    top = name_heading.locator("xpath=ancestor::section[1]")
    if await top.count() == 0:
        top = name_heading.locator("..")
    visible_text = (await top.inner_text()).strip()
    if not visible_text:
        raise ParserDriftError("LinkedIn member profile introduction is empty.")
    return top, name, visible_text


async def _top_card_fields(
    top: Locator,
    name: str,
    visible_text: str,
) -> tuple[
    str | None,
    str | None,
    str | None,
    PersonConnectionDegree | None,
    str | None,
    str | None,
]:
    lines = unique_lines(visible_text)
    auxiliary_lines = {
        line
        for value in await top.locator(
            'a[href*="/trust/verification/"], a[href*="/verify/"]'
        ).all_inner_texts()
        for line in unique_lines(value)
    }
    try:
        name_index = lines.index(name)
    except ValueError:
        name_index = 0
    candidates = lines[name_index + 1 :]
    pronouns = next(
        (
            line
            for line in candidates[:3]
            if "/" in line
            and len(line) <= 80
            and (
                (line.startswith("(") and line.endswith(")"))
                or re.fullmatch(r"[A-Za-z]+(?:/[A-Za-z]+)+", line)
            )
        ),
        None,
    )
    headline = next(
        (
            line
            for line in candidates
            if line != pronouns
            and line not in auxiliary_lines
            and line.casefold() not in ACTION_LINES
            and not CONNECTION_DEGREE_PATTERN.fullmatch(line.strip(" ·•"))
            and not CONNECTION_COUNT_PATTERN.search(line)
            and not FOLLOWER_COUNT_PATTERN.search(line)
            and line.casefold() != "contact info"
        ),
        None,
    )
    contact_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.casefold().strip(" ·•").startswith("contact info")
        ),
        -1,
    )
    location = None
    if contact_index > 0:
        location = next(
            (
                candidate
                for candidate in reversed(lines[:contact_index])
                if candidate not in {name, headline, pronouns}
                and candidate not in auxiliary_lines
                and candidate.strip(" ·•")
                and not CONNECTION_DEGREE_PATTERN.fullmatch(candidate.strip(" ·•"))
                and not CONNECTION_COUNT_PATTERN.search(candidate)
                and not FOLLOWER_COUNT_PATTERN.search(candidate)
            ),
            None,
        )
    connection_count = _first_pattern_text(lines, CONNECTION_COUNT_PATTERN)
    follower_count = _first_pattern_text(lines, FOLLOWER_COUNT_PATTERN)
    return (
        pronouns,
        headline,
        location,
        PersonConnectionDegree(value)
        if (value := connection_degree(visible_text)) is not None
        else None,
        connection_count,
        follower_count,
    )


def _merge_sections(
    main_sections: tuple[PersonProfileSection, ...],
    detail_sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonProfileSection, ...]:
    values: dict[str, PersonProfileSection] = {section.key: section for section in main_sections}
    for section in detail_sections:
        values[section.key] = section
    return tuple(values.values())


class PersonProfilePage:
    def __init__(self, playwright: LinkedInPlaywright, *, max_detail_pages: int) -> None:
        if max_detail_pages < 0:
            raise ValueError("Profile detail-page bound cannot be negative.")
        self._playwright = playwright
        self._max_detail_pages = max_detail_pages

    async def read(
        self,
        request: PeopleGetInput,
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        captures: list[PersonProfilePageCapture] = []
        detail_sections: list[PersonProfileSection] = []
        read_all_sections = request.sections == (PersonProfileSectionSelector.ALL,)
        requested_section_keys = (
            None
            if read_all_sections
            else {
                section.value
                for section in request.sections
                if section is not PersonProfileSectionSelector.OVERVIEW
            }
        )
        async with self._playwright.page() as page:
            await page.goto(canonical_profile_url(request.profile_slug))
            try:
                await (
                    page.locator("main")
                    .get_by_role("heading")
                    .first.wait_for(
                        state="visible",
                        timeout=10_000,
                    )
                )
            except PlaywrightTimeoutError as error:
                raise ParserDriftError("LinkedIn member profile has no visible heading.") from error
            main = page.locator("main")
            await _top_card(main)
            await page.wait_for_timeout(2_000)
            await _expand_and_scroll(page)
            main = page.locator("main")
            top, name, top_text = await _top_card(main)
            (
                pronouns,
                headline,
                location,
                connection_degree,
                connection_count_text,
                follower_count_text,
            ) = await _top_card_fields(top, name, top_text)
            current_company_text = await first_text(top.locator('a[href*="/company/"]'))
            if current_company_text is None:
                current_company_text = await first_text(
                    top.locator('[role="button"]:has(svg[id^="company-accent-"])')
                )
            education_summary_text = await first_text(top.locator('a[href*="/school/"]'))
            if education_summary_text is None:
                education_summary_text = await first_text(
                    top.locator('[role="button"]:has(svg[id^="school-accent-"])')
                )
            actual_slug = profile_slug_from_url(page.url) or request.profile_slug
            profile_url = canonical_profile_url(actual_slug)
            main_text = await _visible_page_text(page)
            main_captured_at = datetime.now(UTC)
            captures.append(
                PersonProfilePageCapture(
                    source_url=HttpUrl(profile_url),
                    page_kind="profile",
                    captured_text=main_text,
                    captured_at=main_captured_at,
                )
            )
            all_main_sections = await _extract_sections(
                main,
                profile_url,
                profile_name=name,
            )
            detail_urls = await _profile_detail_urls(main, actual_slug)
            detail_pairs = tuple((url, _detail_section_key(url)) for url in detail_urls)
            selected_detail_pairs = (
                detail_pairs
                if requested_section_keys is None
                else tuple(pair for pair in detail_pairs if pair[1] in requested_section_keys)
            )
            visited_detail_pairs = selected_detail_pairs[: self._max_detail_pages]
            truncated_detail_pairs = selected_detail_pairs[self._max_detail_pages :]
            main_sections = (
                all_main_sections
                if requested_section_keys is None
                else tuple(
                    section
                    for section in all_main_sections
                    if section.key in requested_section_keys
                )
            )

            for detail_url, _detail_key in visited_detail_pairs:
                await page.goto(detail_url)
                await _expand_and_scroll(page)
                detail_text = await _visible_page_text(page)
                page_sections = await _extract_sections(
                    page.locator("main"),
                    detail_url,
                    profile_name=name,
                )
                section_heading = page_sections[0].heading if page_sections else "Profile section"
                captures.append(
                    PersonProfilePageCapture(
                        source_url=HttpUrl(detail_url),
                        page_kind="section",
                        section_heading=section_heading,
                        captured_text=detail_text,
                        captured_at=datetime.now(UTC),
                    )
                )
                detail_sections.extend(page_sections)

        sections = _merge_sections(main_sections, tuple(detail_sections))
        experiences = _parse_experiences(sections)
        education = _parse_education(sections)
        about_section = next(
            (
                section
                for section in sections
                if section.heading.casefold() == "about" or section.key == "about"
            ),
            None,
        )
        about = _section_body(about_section) if about_section else None
        captured_at = datetime.now(UTC)
        returned_sections = tuple(
            dict.fromkeys(("overview", *(section.key for section in sections)))
        )
        returned_section_set = set(returned_sections)
        unavailable_sections = tuple(
            section
            for section in request.sections
            if section is not PersonProfileSectionSelector.ALL
            and section.value not in returned_section_set
        )
        coverage = PersonProfileCoverage(
            pages_visited=len(captures),
            detail_pages_discovered=len(detail_urls),
            detail_pages_visited=len(visited_detail_pairs),
            detail_page_limit=self._max_detail_pages,
            truncated=bool(truncated_detail_pairs),
            captured_at=captured_at,
            requested_sections=request.sections,
            returned_sections=returned_sections,
            detail_sections_discovered=tuple(dict.fromkeys(section for _, section in detail_pairs)),
            detail_sections_visited=tuple(
                dict.fromkeys(section for _, section in visited_detail_pairs)
            ),
            unavailable_sections=unavailable_sections,
            truncated_sections=tuple(
                dict.fromkeys(section for _, section in truncated_detail_pairs)
            ),
        )
        combined_text = "\n\n".join(
            f"--- source: {capture.source_url} ---\n{capture.captured_text}" for capture in captures
        )
        main_url = captures[0].source_url
        evidence_values = (
            ("name", name, main_url),
            ("pronouns", pronouns, main_url),
            ("headline", headline, main_url),
            ("location", location, main_url),
            ("connection_count_text", connection_count_text, main_url),
            ("follower_count_text", follower_count_text, main_url),
            ("current_company_text", current_company_text, main_url),
            ("education_summary_text", education_summary_text, main_url),
            (
                "about",
                about,
                about_section.source_url if about_section else main_url,
            ),
        )
        evidence = tuple(
            PersonProfileEvidence(field=field, quote=value, source_url=source_url)
            for field, value, source_url in evidence_values
            if value
        )
        observation = PersonProfileObservation(
            profile_slug=actual_slug,
            profile_url=HttpUrl(profile_url),
            name=name,
            pronouns=pronouns,
            headline=headline,
            location=location,
            connection_degree=connection_degree,
            connection_count_text=connection_count_text,
            follower_count_text=follower_count_text,
            current_company_text=current_company_text,
            education_summary_text=education_summary_text,
            about=about,
            experiences=experiences,
            education=education,
            sections=sections,
            visible_text=combined_text,
            evidence=evidence,
            coverage=coverage,
            captured_at=captured_at,
        )
        return observation, tuple(captures)
