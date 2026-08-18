"""Visible LinkedIn page implementation for `linkedin_mcp.tools.companies.get.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.companies.get.models.company_get_input import CompanyGetInput
from linkedin_mcp.tools.companies.get.models.company_profile_coverage import CompanyProfileCoverage
from linkedin_mcp.tools.companies.get.models.company_profile_evidence import CompanyProfileEvidence
from linkedin_mcp.tools.companies.get.models.company_profile_observation import (
    CompanyProfileObservation,
)
from linkedin_mcp.tools.companies.get.models.company_profile_page_capture import (
    CompanyProfilePageCapture,
)
from linkedin_mcp.tools.companies.surface import (
    ACTION_LINES,
    ASSOCIATED_MEMBER_PATTERN,
    FOLLOWER_COUNT_PATTERN,
    INITIAL_RESULTS_POLL_ATTEMPTS,
    INITIAL_RESULTS_POLL_DELAY_MS,
    VISIBLE_COUNT,
    expand_and_scroll,
    first_visible_text,
    unique_lines,
)
from linkedin_mcp.ui import LinkedInLocator as Locator
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.urls import (
    canonical_company_url,
    company_slug_from_url,
)

_EXPLICIT_ASSOCIATED_MEMBER_PATTERN = re.compile(
    rf"\b{VISIBLE_COUNT}\s+associated\s+members?\b",
    re.IGNORECASE,
)

_COMPANY_SIZE_PATTERN = re.compile(
    r"\b(?:self-employed|(?:1|11|51|201|501|1,001|5,001|10,001)"
    r"\s*-\s*(?:10|50|200|500|1,000|5,000|10,000)|10,001\+)"
    r"\s+employees?\b",
    re.IGNORECASE,
)

_ABOUT_FIELD_LABELS = (
    "Website",
    "Industry",
    "Company size",
    "Headquarters",
    "Type",
    "Founded",
    "Specialties",
)


async def _company_heading(main: Locator, page: Page) -> str:
    heading = await first_visible_text(main.get_by_role("heading", level=1))
    if heading:
        return unique_lines(heading)[0]
    title = await page.title()
    candidate = re.split(r"\s*[|·]\s*LinkedIn", title, maxsplit=1)[0].strip()
    main_text = (await main.inner_text()).strip()
    if not candidate or candidate not in {line.strip() for line in main_text.splitlines()}:
        raise ParserDriftError("LinkedIn company profile has no exact visible company name.")
    return candidate


async def _top_company_region(main: Locator, name: str) -> Locator:
    headings = main.get_by_role(
        "heading",
        name=re.compile(rf"^{re.escape(name)}$"),
    )
    for index in range(await headings.count()):
        heading = headings.nth(index)
        if not await heading.is_visible():
            continue
        region = heading.locator("..")
        for _ in range(8):
            lines = unique_lines((await region.inner_text()).strip())
            if name in lines and any(line != name for line in lines):
                return region
            region = region.locator("..")
    raise ParserDriftError("LinkedIn company profile has no unique visible introduction.")


def _line_after_label(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if line.casefold().rstrip(":") == label.casefold():
            return lines[index + 1] if index + 1 < len(lines) else None
    return None


async def _about_region(main: Locator) -> Locator:
    candidates = main.get_by_role(
        "heading",
        name=re.compile(r"^(?:About|Overview)$", re.IGNORECASE),
    )
    for attempt in range(INITIAL_RESULTS_POLL_ATTEMPTS):
        regions: dict[
            tuple[str, tuple[float, float, float, float] | None],
            tuple[Locator, bool],
        ] = {}
        for index in range(await candidates.count()):
            heading = candidates.nth(index)
            if not await heading.is_visible():
                continue
            ancestor = heading.locator("xpath=ancestor::section[1]")
            region = ancestor.first if await ancestor.count() else heading.locator("..")
            if not await region.is_visible():
                continue
            text = (await region.inner_text()).strip()
            if not text:
                continue
            lines = unique_lines(text)
            labels = {line.casefold().rstrip(":") for line in lines}
            contains_about_field = any(label.casefold() in labels for label in _ABOUT_FIELD_LABELS)
            box = await region.bounding_box()
            bounds = (
                (
                    box["x"],
                    box["y"],
                    box["width"],
                    box["height"],
                )
                if box is not None
                else None
            )
            regions.setdefault(("\n".join(lines), bounds), (region, contains_about_field))
        if len(regions) == 1:
            return next(iter(regions.values()))[0]
        qualified = [region for region, has_field in regions.values() if has_field]
        if len(qualified) == 1:
            return qualified[0]
        if attempt + 1 < INITIAL_RESULTS_POLL_ATTEMPTS:
            await main.page.wait_for_timeout(INITIAL_RESULTS_POLL_DELAY_MS)
    raise ParserDriftError("LinkedIn company About page has no unique visible About section.")


def _about_description(visible_text: str) -> str | None:
    lines = visible_text.strip().splitlines()
    while lines and lines[0].strip().casefold() in {"about", "overview"}:
        lines.pop(0)
    value = "\n".join(lines).strip()
    boundaries = tuple(
        match.start()
        for label in _ABOUT_FIELD_LABELS
        if (
            match := re.search(
                rf"(?im)^\s*{re.escape(label)}:?\s*$",
                value,
            )
        )
        is not None
    )
    if boundaries:
        value = value[: min(boundaries)]
    value = value.strip()
    return value or None


async def _about_website_url(region: Locator) -> HttpUrl | None:
    anchors = region.locator("a[href]")
    values: list[HttpUrl] = []
    for index in range(min(await anchors.count(), 100)):
        link = anchors.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        label = (await link.inner_text()).strip()
        if not href:
            continue
        absolute_url = urljoin("https://www.linkedin.com", href)
        parsed = urlsplit(absolute_url)
        host = (parsed.hostname or "").casefold()
        if host in {"linkedin.com", "www.linkedin.com"} and parsed.path.startswith(
            "/redir/redirect"
        ):
            redirect_targets = parse_qs(parsed.query).get("url", ())
            if len(redirect_targets) == 1:
                absolute_url = redirect_targets[0]
                parsed = urlsplit(absolute_url)
                host = (parsed.hostname or "").casefold()
        if "website" not in label.casefold() and host in {"linkedin.com", "www.linkedin.com"}:
            continue
        value = HttpUrl(absolute_url)
        if value not in values:
            values.append(value)
    if len(values) > 1:
        raise ParserDriftError("LinkedIn company About page exposes multiple website targets.")
    return values[0] if values else None


def _evidence_source_url(
    captures: list[CompanyProfilePageCapture],
    *,
    field: str,
    quote: str,
    preferred_url: HttpUrl,
) -> HttpUrl:
    preferred = next(
        (
            capture.source_url
            for capture in captures
            if str(capture.source_url) == str(preferred_url) and quote in capture.captured_text
        ),
        None,
    )
    if preferred is not None:
        return preferred
    matching = next(
        (capture.source_url for capture in captures if quote in capture.captured_text),
        None,
    )
    if matching is None:
        raise ParserDriftError(f"Company field {field!r} has no exact captured-source quote.")
    return matching


class CompanyProfilePage:
    def __init__(self, playwright: LinkedInPlaywright) -> None:
        self._playwright = playwright

    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]:
        captures: list[CompanyProfilePageCapture] = []
        async with self._playwright.page() as page:
            await page.goto(canonical_company_url(request.company_slug))
            await expand_and_scroll(page)
            overview_main = page.locator("main")
            name = await _company_heading(overview_main, page)
            top = await _top_company_region(overview_main, name)
            top_text = (await top.inner_text()).strip()
            actual_slug = company_slug_from_url(page.url) or request.company_slug
            company_url = canonical_company_url(actual_slug)
            overview_text = (await overview_main.inner_text()).strip()
            captures.append(
                CompanyProfilePageCapture(
                    source_url=HttpUrl(company_url),
                    page_kind="overview",
                    captured_text=overview_text,
                    captured_at=datetime.now(UTC),
                )
            )
            about_url = canonical_company_url(actual_slug, "about")
            await page.goto(about_url)
            await expand_and_scroll(page)
            about_main = page.locator("main")
            about_name = await _company_heading(about_main, page)
            about_slug = company_slug_from_url(page.url) or actual_slug
            if about_name != name or about_slug != actual_slug:
                raise ParserDriftError(
                    "LinkedIn company About page conflicts with the overview identity."
                )
            about_region = await _about_region(about_main)
            about_region_text = (await about_region.inner_text()).strip()
            about_text = (await about_main.inner_text()).strip()
            website_url = await _about_website_url(about_region)
            captures.append(
                CompanyProfilePageCapture(
                    source_url=HttpUrl(about_url),
                    page_kind="about",
                    captured_text=about_text,
                    captured_at=datetime.now(UTC),
                )
            )

        all_lines = unique_lines("\n".join(capture.captured_text for capture in captures))
        description = _about_description(about_region_text)
        company_size_line = _line_after_label(all_lines, "Company size")
        company_size_match = _COMPANY_SIZE_PATTERN.search(
            company_size_line or ""
        ) or _COMPANY_SIZE_PATTERN.search("\n".join(all_lines))
        all_text = "\n".join(all_lines)
        member_match = _EXPLICIT_ASSOCIATED_MEMBER_PATTERN.search(
            all_text
        ) or ASSOCIATED_MEMBER_PATTERN.search(top_text)
        follower_match = FOLLOWER_COUNT_PATTERN.search(top_text)
        specialties_text = _line_after_label(all_lines, "Specialties")
        specialties = tuple(
            value.strip() for value in (specialties_text or "").split(",") if value.strip()
        )
        captured_at = datetime.now(UTC)
        coverage = CompanyProfileCoverage(captured_at=captured_at)
        combined_text = "\n\n".join(
            f"--- source: {capture.source_url} ---\n{capture.captured_text}" for capture in captures
        )
        main_url = captures[0].source_url
        about_source_url = captures[1].source_url
        tagline = next(
            (
                line
                for line in unique_lines(top_text)[1:]
                if line != name
                and line.casefold() not in ACTION_LINES
                and not FOLLOWER_COUNT_PATTERN.search(line)
                and not ASSOCIATED_MEMBER_PATTERN.search(line)
            ),
            None,
        )
        values = (
            ("name", name, main_url),
            ("tagline", tagline, main_url),
            ("description", description, about_source_url),
            ("industry", _line_after_label(all_lines, "Industry"), about_source_url),
            (
                "company_size_range",
                company_size_match.group(0) if company_size_match else None,
                about_source_url,
            ),
            (
                "associated_member_count_text",
                member_match.group(0) if member_match else None,
                main_url,
            ),
            (
                "follower_count_text",
                follower_match.group(0) if follower_match else None,
                main_url,
            ),
            ("headquarters", _line_after_label(all_lines, "Headquarters"), about_source_url),
            ("organization_type", _line_after_label(all_lines, "Type"), about_source_url),
            ("founded_text", _line_after_label(all_lines, "Founded"), about_source_url),
        )
        evidence = tuple(
            CompanyProfileEvidence(
                field=field,
                quote=value,
                source_url=_evidence_source_url(
                    captures,
                    field=field,
                    quote=value,
                    preferred_url=source_url,
                ),
            )
            for field, value, source_url in values
            if value
        )
        observation = CompanyProfileObservation(
            company_slug=actual_slug,
            company_url=HttpUrl(company_url),
            name=name,
            tagline=tagline,
            description=description,
            website_url=website_url,
            industry=_line_after_label(all_lines, "Industry"),
            company_size_range=(company_size_match.group(0) if company_size_match else None),
            associated_member_count_text=(member_match.group(0) if member_match else None),
            follower_count_text=(follower_match.group(0) if follower_match else None),
            headquarters=_line_after_label(all_lines, "Headquarters"),
            organization_type=_line_after_label(all_lines, "Type"),
            founded_text=_line_after_label(all_lines, "Founded"),
            specialties=specialties,
            visible_text=combined_text,
            evidence=evidence,
            coverage=coverage,
            captured_at=captured_at,
        )
        return observation, tuple(captures)
