"""Visible LinkedIn page implementation for `linkedin_mcp.tools.jobs.get.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.models import EvidenceField
from linkedin_mcp.tools._shared.urls import (
    canonical_job_url,
    canonical_profile_url,
    profile_slug_from_url,
)
from linkedin_mcp.tools.jobs.get.models.job_apply_method import JobApplyMethod
from linkedin_mcp.tools.jobs.get.models.job_detail_input import JobDetailInput
from linkedin_mcp.tools.jobs.get.models.job_detail_observation import JobDetailObservation
from linkedin_mcp.tools.jobs.get.models.job_hiring_team_member import JobHiringTeamMember
from linkedin_mcp.tools.jobs.models.job_workplace_type import JobWorkplaceType
from linkedin_mcp.tools.jobs.surface import (
    LISTED_PATTERN,
    WORKPLACE_LABELS,
    WORKPLACE_VALUES,
    first_href,
    first_pattern_text,
    first_text,
)
from linkedin_mcp.tools.jobs.surface import (
    lines as visible_text_lines,
)

_EMPLOYMENT_TYPES = (
    "Full-time",
    "Part-time",
    "Contract",
    "Temporary",
    "Internship",
    "Volunteer",
    "Other",
)

_WORKPLACE_TYPES = ("Remote", "Hybrid", "On-site")

_APPLICANT_PATTERN = re.compile(
    r"\b(?:(?:over|under)\s+)?[\d,.+]+\s+(?:applicants?|people clicked apply)\b",
    re.IGNORECASE,
)

_DETAIL_ACTION_LINES = frozenset({"apply", "save", "easy apply"})

_DETAIL_NOISE_PREFIXES = (
    "promoted by",
    "responses managed",
    "use ai to",
    "get ai-powered",
    "show match details",
    "tailor my resume",
    "help me stand out",
)

_CONNECTION_DEGREE_PATTERN = re.compile(r"^[•·]?\s*(?:1st|2nd|3rd|\d+(?:st|nd|rd|th))$", re.I)


def _metadata_location(lines: list[str]) -> str | None:
    for line in lines[:12]:
        match = LISTED_PATTERN.search(line)
        if match is None:
            continue
        candidate = line[: match.start()].strip(" \t·•")
        if candidate:
            return candidate
    return None


def _fallback_location(
    lines: list[str],
    *,
    excluded: set[str | None],
) -> str | None:
    exact_noise = {
        *(value.casefold() for value in _EMPLOYMENT_TYPES),
        *(value.casefold() for value in _WORKPLACE_TYPES),
        *_DETAIL_ACTION_LINES,
    }
    for line in lines[:12]:
        lowered = line.casefold()
        if (
            line in excluded
            or lowered in exact_noise
            or LISTED_PATTERN.search(line)
            or _APPLICANT_PATTERN.search(line)
            or lowered == "about the job"
            or any(lowered.startswith(prefix) for prefix in _DETAIL_NOISE_PREFIXES)
        ):
            continue
        return line
    return None


def _visible_workplace(lines: list[str]) -> JobWorkplaceType | None:
    for line in lines:
        value = WORKPLACE_VALUES.get(line.casefold())
        if value is not None:
            return value
    return None


async def _job_top_card(main: Locator, job_id: str) -> Locator:
    save_control = main.get_by_role(
        "button",
        name=re.compile(r"^save (?:the )?job$", re.I),
    ).first
    if await save_control.count() == 0:
        raise ParserDriftError("LinkedIn job detail has no identifiable primary job card.")
    candidate = save_control
    for _ in range(8):
        candidate = candidate.locator("..")
        attribute_links = candidate.locator(f'a[href="{canonical_job_url(job_id)}"]')
        if await attribute_links.count() > 0:
            return candidate
    raise ParserDriftError("LinkedIn job detail has no identifiable primary job card.")


async def _about_job_container(main: Locator) -> tuple[Locator, Locator]:
    about_heading = main.get_by_role(
        "heading",
        name=re.compile(r"^about the job$", re.I),
    ).first
    if await about_heading.count() == 0:
        raise ParserDriftError("LinkedIn job detail has no visible About the job section.")
    container = about_heading
    for _ in range(5):
        container = container.locator("..")
        boxes = container.locator('[data-testid="expandable-text-box"]')
        if await boxes.count() > 0:
            return container, boxes.first
    raise ParserDriftError("LinkedIn job detail has no current expandable About the job content.")


async def _visible_hiring_team(
    main: Locator,
) -> tuple[tuple[JobHiringTeamMember, ...], str | None]:
    marker = main.get_by_text("Meet the hiring team", exact=True)
    if await marker.count() == 0:
        return (), None
    container = marker.first.locator("..")
    section_text = (await container.inner_text()).strip()
    if not section_text:
        return (), None

    links = container.locator('a[href*="/in/"]')
    links_by_slug: dict[str, list[Locator]] = {}
    for index in range(await links.count()):
        link = links.nth(index)
        href = await link.get_attribute("href")
        if not href:
            continue
        absolute_href = urljoin("https://www.linkedin.com", href)
        profile_slug = profile_slug_from_url(absolute_href)
        if profile_slug:
            links_by_slug.setdefault(profile_slug, []).append(link)

    members: list[JobHiringTeamMember] = []
    for profile_slug, matching_links in links_by_slug.items():
        visible_values = [
            (await link.inner_text()).strip() for link in matching_links if await link.is_visible()
        ]
        visible_values = [value for value in visible_values if value]
        if not visible_values:
            continue
        visible_text = max(visible_values, key=len).strip(" \x7f")
        lines = [line.strip(" \x7f") for line in visible_text_lines(visible_text)]
        name_candidates = [
            candidate_lines[0].strip(" \x7f")
            for value in visible_values
            if (candidate_lines := visible_text_lines(value))
        ]
        if not name_candidates:
            continue
        name = min(name_candidates, key=len)
        connection_degree_text = next(
            (line for line in lines if _CONNECTION_DEGREE_PATTERN.fullmatch(line)),
            None,
        )
        mutual_connections_text = next(
            (line for line in lines if "mutual connection" in line.casefold()),
            None,
        )
        role_text = next(
            (
                line
                for line in lines
                if line.casefold() in {"job poster", "hiring manager", "recruiter"}
            ),
            None,
        )
        headline = next(
            (
                line
                for line in lines
                if line
                not in {
                    name,
                    connection_degree_text,
                    mutual_connections_text,
                    role_text,
                    "Message",
                }
            ),
            None,
        )
        members.append(
            JobHiringTeamMember(
                profile_slug=profile_slug,
                profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                name=name,
                headline=headline,
                connection_degree_text=connection_degree_text,
                role_text=role_text,
                mutual_connections_text=mutual_connections_text,
                visible_text=visible_text,
            )
        )
    return tuple(members), section_text


async def _visible_job_title(
    page: Page,
    main: Locator,
    *,
    visible_text: str,
    company_name: str | None,
) -> str:
    semantic_title = await first_text(main.get_by_role("heading", level=1))
    if semantic_title:
        semantic_lines = visible_text_lines(semantic_title)
        if semantic_lines and all(line == semantic_lines[0] for line in semantic_lines):
            return semantic_lines[0]
        return semantic_title

    visible_lines = visible_text_lines(visible_text)
    document_title = (await page.title()).strip()
    linkedin_suffix = " | LinkedIn"
    if document_title.endswith(linkedin_suffix):
        title_and_company = document_title[: -len(linkedin_suffix)]
        if company_name:
            company_suffix = f" | {company_name}"
            if title_and_company.endswith(company_suffix):
                title_and_company = title_and_company[: -len(company_suffix)]
        candidate = title_and_company.strip()
        if candidate and candidate in visible_lines:
            return candidate

    if company_name:
        for index, line in enumerate(visible_lines[:-1]):
            if line != company_name:
                continue
            candidate = visible_lines[index + 1]
            if candidate and len(candidate) <= 500:
                return candidate

    raise ParserDriftError("LinkedIn job detail has no confidently identifiable visible title.")


async def _visible_description(description_box: Locator) -> str:
    description = (await description_box.inner_text()).strip()
    description = re.sub(r"\s*(?:…|\.\.\.)\s*more\s*$", "", description, flags=re.I).strip()
    if not description:
        raise ParserDriftError("LinkedIn job detail has an empty About the job description.")
    return description


class JobDetailPage:
    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_job_url(request.job_id))
            await self._wait_until_ready(page, request.job_id)
            await self._expand_description(page)
            return await self.extract_visible_job(page, request.job_id)

    @staticmethod
    async def _wait_until_ready(page: Page, job_id: str) -> None:
        main = page.locator("main")
        about_heading = main.get_by_role(
            "heading",
            name=re.compile(r"^about the job$", re.I),
        )
        save_control = main.get_by_role(
            "button",
            name=re.compile(r"^save (?:the )?job$", re.I),
        )
        try:
            await main.first.wait_for(state="visible")
            await about_heading.first.wait_for(state="visible")
            await save_control.first.wait_for(state="visible")
            await main.locator(f'a[href="{canonical_job_url(job_id)}"]').first.wait_for(
                state="visible"
            )
            await main.locator('[data-testid="expandable-text-box"]').first.wait_for(
                state="visible"
            )
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                "LinkedIn job detail did not render its visible About the job section."
            ) from error

    async def _expand_description(self, page: Page) -> None:
        main = page.locator("main").first
        _, description_box = await _about_job_container(main)
        expand_button = description_box.locator('[data-testid="expandable-text-button"]')
        if await expand_button.count() == 0:
            return
        before_height = await description_box.evaluate(
            "element => element.getBoundingClientRect().height"
        )
        spans = expand_button.locator("span")
        click_target = spans.last if await spans.count() > 0 else expand_button
        try:
            await self._browser.click_visible_control(page, click_target)
        except PlaywrightError as error:
            raise ParserDriftError(
                "LinkedIn job detail exposed its description expansion control "
                "but it could not be activated."
            ) from error

        for _ in range(20):
            if await expand_button.count() == 0:
                return
            current_height = await description_box.evaluate(
                "element => element.getBoundingClientRect().height"
            )
            if current_height > before_height:
                return
            await page.wait_for_timeout(100)
        raise ParserDriftError(
            "LinkedIn job detail did not visibly expand its About the job description."
        )

    @staticmethod
    async def extract_visible_job(page: Page, job_id: str) -> JobDetailObservation:
        main = page.locator("main").first
        if await main.count() == 0:
            raise ParserDriftError("LinkedIn job detail returned no visible text.")

        top_card = await _job_top_card(main, job_id)
        top_text = (await top_card.inner_text()).strip()
        if not top_text:
            raise ParserDriftError("LinkedIn job detail returned an empty primary job card.")
        company_link = top_card.locator('a[href*="/company/"]')
        company_name = await first_text(company_link)
        company_href = await first_href(company_link)
        company_url = (
            HttpUrl(urljoin("https://www.linkedin.com", company_href)) if company_href else None
        )

        lines = visible_text_lines(top_text)
        title = await _visible_job_title(
            page,
            top_card,
            visible_text=top_text,
            company_name=company_name,
        )
        attribute_lines: list[str] = []
        attribute_links = top_card.locator(f'a[href="{canonical_job_url(job_id)}"]')
        for index in range(await attribute_links.count()):
            attribute_lines.extend(
                visible_text_lines(await attribute_links.nth(index).inner_text())
            )
        semantic_lines = [*lines, *attribute_lines]

        listed_at_text = first_pattern_text(lines, LISTED_PATTERN)
        applicant_text = first_pattern_text(lines, _APPLICANT_PATTERN)
        employment_type = next(
            (
                value
                for value in _EMPLOYMENT_TYPES
                if any(line.casefold() == value.casefold() for line in semantic_lines[:20])
            ),
            None,
        )
        workplace_type = _visible_workplace(semantic_lines[:20])

        excluded = {title, company_name, listed_at_text, applicant_text, employment_type}
        location = _metadata_location(lines) or _fallback_location(lines, excluded=excluded)

        easy_apply_control = top_card.get_by_role(
            "link",
            name=re.compile(r"easy apply", re.I),
        )
        if await easy_apply_control.count() == 0:
            easy_apply_control = top_card.get_by_role(
                "button",
                name=re.compile(r"easy apply", re.I),
            )
        external_apply_control = top_card.get_by_role(
            "button",
            name=re.compile(r"^apply(?: on company website)?$", re.I),
        )
        if await easy_apply_control.count() > 0:
            apply_method = JobApplyMethod.EASY_APPLY
            application_quote = "Easy Apply"
        elif await external_apply_control.count() > 0:
            apply_method = JobApplyMethod.EXTERNAL
            application_quote = "Apply"
        else:
            apply_method = JobApplyMethod.UNAVAILABLE
            application_quote = None

        metadata_line = next(
            (
                line
                for line in lines
                if LISTED_PATTERN.search(line) or _APPLICANT_PATTERN.search(line)
            ),
            None,
        )
        excluded_lines = {
            title,
            company_name,
            metadata_line,
            employment_type,
            *(_WORKPLACE_TYPES),
            "Easy Apply",
            "Apply",
            "Save",
        }
        insights = tuple(line for line in lines if line not in excluded_lines)
        promoted = any(line.casefold().startswith("promoted") for line in insights)

        _, description_box = await _about_job_container(main)
        description_text = await _visible_description(description_box)
        hiring_team, hiring_team_text = await _visible_hiring_team(main)
        visible_text = "\n\n".join(
            value
            for value in (
                top_text,
                hiring_team_text,
                f"About the job\n\n{description_text}",
            )
            if value
        )

        evidence_values: list[tuple[str, str | None]] = [
            ("title", title),
            ("company_name", company_name),
            ("location", location),
            (
                "workplace_type",
                WORKPLACE_LABELS.get(workplace_type) if workplace_type is not None else None,
            ),
            ("employment_type", employment_type),
            ("listed_at_text", listed_at_text),
            ("applicant_text", applicant_text),
            ("description_text", description_text),
            ("apply_method", application_quote),
            (
                "promoted",
                next(
                    (line for line in insights if line.casefold().startswith("promoted")),
                    None,
                ),
            ),
        ]
        evidence_values.extend(
            (f"insights.{index}", insight) for index, insight in enumerate(insights)
        )
        for index, member in enumerate(hiring_team):
            evidence_values.append((f"hiring_team.{index}.name", member.name))
            if member.headline:
                evidence_values.append((f"hiring_team.{index}.headline", member.headline))
        evidence = tuple(
            EvidenceField(field=field, quote=value)
            for field, value in evidence_values
            if value and value in visible_text
        )
        return JobDetailObservation(
            job_id=job_id,
            job_url=HttpUrl(canonical_job_url(job_id)),
            title=title,
            company_name=company_name,
            company_url=company_url,
            location=location,
            workplace_type=workplace_type,
            employment_type=employment_type,
            listed_at_text=listed_at_text,
            applicant_text=applicant_text,
            description_text=description_text,
            apply_method=apply_method,
            easy_apply=apply_method is JobApplyMethod.EASY_APPLY,
            promoted=promoted,
            insights=insights,
            hiring_team=hiring_team,
            visible_text=visible_text,
            evidence=evidence,
            captured_at=datetime.now(UTC),
        )
