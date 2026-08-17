"""Current visible LinkedIn invitation inventory and exact-count collection."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.errors import BrowserUnavailableError, ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.collections import wait_for_collection_change
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools.invitations.list.models.invitation_available_action import (
    InvitationAvailableAction,
)
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_entity import InvitationEntity
from linkedin_mcp.tools.invitations.list.models.invitation_entity_type import InvitationEntityType
from linkedin_mcp.tools.invitations.list.models.invitation_evidence import InvitationEvidence
from linkedin_mcp.tools.invitations.list.models.invitation_filter import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    InvitationFilter,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_coverage import (
    InvitationListCoverage,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput
from linkedin_mcp.tools.invitations.list.models.invitation_summary import InvitationSummary
from linkedin_mcp.tools.invitations.list.models.invitation_type import InvitationType

InvitationProgressReporter = Callable[[int, int, str], Awaitable[None]]

_RECEIVED_ROOT_URL = "https://www.linkedin.com/mynetwork/invitation-manager/received/"
_SENT_ROOT_URL = "https://www.linkedin.com/mynetwork/invitation-manager/sent/"
_SENT_ROOT_PATH = "/mynetwork/invitation-manager/sent"
_SENT_PEOPLE_PATH = "/mynetwork/invitation-manager/sent/CONNECTION"
_MAX_RAW_CARDS = 5_000
_SETTLE_ATTEMPTS = 8
_SETTLE_DELAY_MS = 250
_INVENTORY_ATTEMPTS = 20
_INVENTORY_DELAY_MS = 250
_SCROLL_DELTA = 3_000
_LINKEDIN_HOSTS = frozenset({"linkedin.com", "www.linkedin.com"})
_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,199}$")
_MUTUAL_PATTERN = re.compile(
    r"\b(?:mutual connections?|you both|same company|same school|also follows?)\b",
    re.IGNORECASE,
)
_TIME_PATTERN = re.compile(
    r"\b(?:today|yesterday|sent|received|\d+\s+"
    r"(?:minute|hour|day|week|month|year)s?\s+ago)\b",
    re.IGNORECASE,
)
_ACTION_TEXT_PATTERN = re.compile(
    r"^(?:accept|ignore|withdraw|connect|message|send a message|reply|show more actions)"
    r"(?:\b|$)",
    re.IGNORECASE,
)
_LOAD_MORE_PATTERN = re.compile(
    r"^(?:load more|show more(?: results)?|see more)$",
    re.IGNORECASE,
)
_ACTION_TARGET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^withdraw invitation sent to (?P<name>.+)$", re.IGNORECASE),
    re.compile(r"^accept invitation for (?P<name>.+)$", re.IGNORECASE),
    re.compile(
        r"^accept (?P<name>.+?)(?:'|\N{RIGHT SINGLE QUOTATION MARK})s invitation$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^accept (?:an )?invitation(?: to connect)? from (?P<name>.+)$",
        re.IGNORECASE,
    ),
)
_INVITATION_TYPE_BY_ENTITY: dict[InvitationEntityType, InvitationType] = {
    InvitationEntityType.PERSON: InvitationType.CONNECTION_REQUEST,
    InvitationEntityType.COMPANY: InvitationType.COMPANY_FOLLOW,
    InvitationEntityType.SCHOOL: InvitationType.SCHOOL_INVITATION,
    InvitationEntityType.GROUP: InvitationType.GROUP_INVITATION,
    InvitationEntityType.EVENT: InvitationType.EVENT_INVITATION,
    InvitationEntityType.NEWSLETTER: InvitationType.NEWSLETTER_INVITATION,
    InvitationEntityType.OTHER: InvitationType.OTHER,
}
_ENTITY_TYPE_BY_PATH: dict[str, InvitationEntityType] = {
    "in": InvitationEntityType.PERSON,
    "company": InvitationEntityType.COMPANY,
    "school": InvitationEntityType.SCHOOL,
    "groups": InvitationEntityType.GROUP,
    "events": InvitationEntityType.EVENT,
    "newsletters": InvitationEntityType.NEWSLETTER,
}
_NAVIGATION_URLS: dict[InvitationDirection, str] = {
    InvitationDirection.RECEIVED: _RECEIVED_ROOT_URL,
    InvitationDirection.SENT: _SENT_ROOT_URL,
}
_COUNT_PATTERNS: dict[InvitationFilter, re.Pattern[str]] = {
    InvitationFilter.FOCUSED: re.compile(
        r"^focused\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.OTHER: re.compile(
        r"^other\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.VERIFIED: re.compile(
        r"^verified\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.MUTUAL_CONNECTIONS: re.compile(
        r"^mutual connections\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.SAME_COMPANY: re.compile(
        r"^your company\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.SAME_SCHOOL: re.compile(
        r"^your school\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
    InvitationFilter.PEOPLE: re.compile(
        r"^people\s*\((?P<count>\d[\d,]*)\)$",
        re.IGNORECASE,
    ),
}
_CONTROL_NAME_PATTERNS: dict[InvitationFilter, re.Pattern[str]] = {
    InvitationFilter.FOCUSED: re.compile(r"^focused\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE),
    InvitationFilter.OTHER: re.compile(r"^other\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE),
    InvitationFilter.VERIFIED: re.compile(r"^verified\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE),
    InvitationFilter.MUTUAL_CONNECTIONS: re.compile(
        r"^mutual connections\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE
    ),
    InvitationFilter.SAME_COMPANY: re.compile(
        r"^your company\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE
    ),
    InvitationFilter.SAME_SCHOOL: re.compile(r"^your school\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE),
    InvitationFilter.PEOPLE: re.compile(r"^people\s*\(\d[\d,]*\)(?:\s|$)", re.IGNORECASE),
}
_CONTROL_OMISSION_GUARD_PATTERNS: dict[InvitationFilter, re.Pattern[str]] = {
    InvitationFilter.VERIFIED: re.compile(
        r"^(?:verified$|verified\s*\([^)]*\)(?:\s|$))",
        re.IGNORECASE,
    ),
    InvitationFilter.MUTUAL_CONNECTIONS: re.compile(
        r"^(?:mutual connections$|mutual connections\s*\([^)]*\)(?:\s|$))",
        re.IGNORECASE,
    ),
    InvitationFilter.SAME_COMPANY: re.compile(
        r"^(?:your company$|your company\s*\([^)]*\)(?:\s|$))",
        re.IGNORECASE,
    ),
    InvitationFilter.SAME_SCHOOL: re.compile(
        r"^(?:your school$|your school\s*\([^)]*\)(?:\s|$))",
        re.IGNORECASE,
    ),
    InvitationFilter.PEOPLE: re.compile(
        r"^(?:people$|people\s*\([^)]*\)(?:\s|$))",
        re.IGNORECASE,
    ),
}
_BUCKET_PICKER_PATTERN = re.compile(
    r"^(?:focused|other)\s*\(\d[\d,]*\)$",
    re.IGNORECASE,
)
_BUCKET_FILTERS = frozenset({InvitationFilter.FOCUSED, InvitationFilter.OTHER})
_CATEGORY_FILTERS = frozenset(
    {
        InvitationFilter.VERIFIED,
        InvitationFilter.MUTUAL_CONNECTIONS,
        InvitationFilter.SAME_COMPANY,
        InvitationFilter.SAME_SCHOOL,
    }
)


@dataclass(frozen=True, slots=True)
class _RawLink:
    href: str
    text: str
    aria_label: str | None
    image_alts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RawControl:
    label: str
    text: str
    href: str | None
    action: str | None


@dataclass(frozen=True, slots=True)
class _RawCard:
    visible_text: str
    explicit_note: str | None
    links: tuple[_RawLink, ...]
    controls: tuple[_RawControl, ...]


@dataclass(frozen=True, slots=True)
class _DomObservation:
    cards: tuple[_RawCard, ...]
    signature: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _VisibleInventory:
    invitation_filter: InvitationFilter
    count: int
    label: str
    advertised: bool = True


@dataclass(frozen=True, slots=True)
class _ParsedEntity:
    entity_type: InvitationEntityType
    entity_url: str | None
    display_name: str
    slug: str | None

    def public(self) -> InvitationEntity:
        material = self.entity_url or f"{self.entity_type.value}\x1f{self.display_name}"
        digest = hashlib.sha256(material.encode()).hexdigest()[:24]
        return InvitationEntity(
            entity_ref=f"entity:{digest}",
            entity_type=self.entity_type,
            entity_url=HttpUrl(self.entity_url) if self.entity_url is not None else None,
            display_name=self.display_name,
            slug=self.slug,
        )


@dataclass(frozen=True, slots=True)
class _ParsedInvitation:
    invitation_ref: str
    direction: InvitationDirection
    invitation_type: InvitationType
    primary_entity: _ParsedEntity
    inviter: _ParsedEntity | None
    headline: str | None
    context: str | None
    note: str | None
    sent_or_received_at_text: str | None
    relationship_context: str | None
    available_actions: tuple[InvitationAvailableAction, ...]
    visible_text: str

    def public(self, *, source_url: str, captured_at: datetime) -> InvitationSummary:
        evidence_values: list[tuple[str, str]] = [
            ("primary_entity.display_name", self.primary_entity.display_name),
        ]
        if self.inviter is not None:
            evidence_values.append(("inviter.display_name", self.inviter.display_name))
        for field_name, value in (
            ("headline", self.headline),
            ("context", self.context),
            ("note", self.note),
            ("sent_or_received_at_text", self.sent_or_received_at_text),
            ("relationship_context", self.relationship_context),
        ):
            if value is not None:
                evidence_values.extend((field_name, line) for line in _lines(value))
        for action in self.available_actions:
            evidence_values.append(("available_actions", action.value))

        evidence: list[InvitationEvidence] = []
        for field_name, quote in evidence_values:
            visible_quote = _matching_visible_quote(self.visible_text, quote)
            if visible_quote is None:
                if field_name == "available_actions":
                    continue
                raise ParserDriftError(
                    f"Invitation field {field_name!r} lacks exact visible evidence."
                )
            evidence.append(
                InvitationEvidence(
                    field=field_name,
                    quote=visible_quote,
                    source_url=HttpUrl(source_url),
                    captured_at=captured_at,
                )
            )
        return InvitationSummary(
            invitation_ref=self.invitation_ref,
            direction=self.direction,
            invitation_type=self.invitation_type,
            primary_entity=self.primary_entity.public(),
            inviter=self.inviter.public() if self.inviter is not None else None,
            headline=self.headline,
            context=self.context,
            note=self.note,
            sent_or_received_at_text=self.sent_or_received_at_text,
            relationship_context=self.relationship_context,
            available_actions=self.available_actions,
            visible_text=self.visible_text,
            evidence=tuple(evidence),
        )


@dataclass(frozen=True, slots=True)
class _CapturedInvitation:
    invitation: _ParsedInvitation
    source_url: str


class _CollectionChanged(Exception):
    pass


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _raw_link(value: object) -> _RawLink | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[str, object], value)
    href = raw.get("href")
    text = raw.get("text")
    aria_label = raw.get("aria_label")
    image_alts = raw.get("image_alts")
    if (
        not isinstance(href, str)
        or not isinstance(text, str)
        or not (isinstance(aria_label, str) or aria_label is None)
        or not isinstance(image_alts, list)
    ):
        return None
    return _RawLink(
        href=href,
        text=text,
        aria_label=aria_label,
        image_alts=tuple(
            item for item in cast(list[object], image_alts) if isinstance(item, str) and item
        ),
    )


def _raw_control(value: object) -> _RawControl | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[str, object], value)
    label = raw.get("label")
    text = raw.get("text")
    href = raw.get("href")
    action = raw.get("action")
    if (
        not isinstance(label, str)
        or not isinstance(text, str)
        or not (isinstance(href, str) or href is None)
        or not (isinstance(action, str) or action is None)
    ):
        return None
    return _RawControl(label=label, text=text, href=href, action=action)


def _raw_card(value: object) -> _RawCard | None:
    if not isinstance(value, dict):
        return None
    raw = cast(dict[str, object], value)
    visible_text = raw.get("visible_text")
    explicit_note = raw.get("explicit_note")
    raw_links = raw.get("links")
    raw_controls = raw.get("controls")
    if (
        not isinstance(visible_text, str)
        or not visible_text.strip()
        or not (isinstance(explicit_note, str) or explicit_note is None)
        or not isinstance(raw_links, list)
        or not isinstance(raw_controls, list)
    ):
        return None
    links = tuple(
        link for item in cast(list[object], raw_links) if (link := _raw_link(item)) is not None
    )
    controls = tuple(
        control
        for item in cast(list[object], raw_controls)
        if (control := _raw_control(item)) is not None
    )
    return _RawCard(
        visible_text=visible_text.strip(),
        explicit_note=_optional_string(explicit_note),
        links=links,
        controls=controls,
    )


def _matching_visible_quote(visible_text: str, value: str) -> str | None:
    if value in visible_text:
        return value
    folded = value.casefold()
    return next((line for line in _lines(visible_text) if line.casefold() == folded), None)


def _action_target_name(card: _RawCard, selected_action: str) -> str | None:
    names: dict[str, str] = {}
    for control in card.controls:
        if control.action != selected_action:
            continue
        for pattern in _ACTION_TARGET_PATTERNS:
            match = pattern.fullmatch(control.label)
            if match is None:
                continue
            name = match.group("name").strip()
            if name:
                names.setdefault(name.casefold(), name)
            break
    if len(names) > 1:
        raise ParserDriftError("An invitation card exposes conflicting action targets.")
    return next(iter(names.values()), None)


def _clean_name_candidate(value: str) -> str | None:
    lines = _lines(value)
    if not lines:
        return None
    candidate = lines[0]
    candidate = re.sub(
        r"\s+(?:verified|premium)$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"(?:'|\N{RIGHT SINGLE QUOTATION MARK})s profile picture$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"\s+(?:open to work,\s*)?profile picture$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"^view\s+(.+?)(?:'|\N{RIGHT SINGLE QUOTATION MARK})s profile$",
        r"\1",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = candidate.strip(" \t\n\r,")
    return candidate or None


def _canonical_entity_link(
    source_url: str,
    href: str,
) -> tuple[InvitationEntityType, str, str] | None:
    parsed = urlsplit(urljoin(source_url, href))
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in _LINKEDIN_HOSTS:
        return None
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    entity_type = _ENTITY_TYPE_BY_PATH.get(parts[0].casefold())
    slug = parts[1]
    if entity_type is None or _SLUG_PATTERN.fullmatch(slug) is None:
        return None
    canonical = f"https://www.linkedin.com/{parts[0].casefold()}/{slug}/"
    return entity_type, slug, canonical


def _entity_candidates(
    card: _RawCard,
    *,
    source_url: str,
) -> dict[str, tuple[InvitationEntityType, str, set[str]]]:
    candidates: dict[str, tuple[InvitationEntityType, str, set[str]]] = {}
    for link in card.links:
        identity = _canonical_entity_link(source_url, link.href)
        if identity is None:
            continue
        entity_type, slug, canonical = identity
        existing = candidates.setdefault(canonical, (entity_type, slug, set()))
        names = existing[2]
        for value in (link.text, link.aria_label or "", *link.image_alts):
            name = _clean_name_candidate(value)
            if name is not None:
                names.add(name)
    return candidates


def _resolve_entity(
    *,
    entity_type: InvitationEntityType,
    slug: str,
    canonical_url: str,
    names: set[str],
    action_name: str | None,
    visible_lines: list[str],
    prefer_action_name: bool,
) -> _ParsedEntity:
    normalized_names = {name.casefold(): name for name in names}
    name: str | None = None
    if prefer_action_name and action_name is not None:
        if action_name.casefold() in normalized_names or any(
            line.casefold() == action_name.casefold() for line in visible_lines
        ):
            name = action_name
        else:
            raise ParserDriftError(
                "The invitation action target conflicts with its visible profile identity."
            )
    if name is None:
        visible_names = {
            line.casefold(): line for line in visible_lines if line.casefold() in normalized_names
        }
        if len(visible_names) == 1:
            name = next(iter(visible_names.values()))
        elif len(normalized_names) == 1:
            name = next(iter(normalized_names.values()))
    if name is None:
        raise ParserDriftError("An invitation entity has no unambiguous visible name.")
    return _ParsedEntity(
        entity_type=entity_type,
        entity_url=canonical_url,
        display_name=name,
        slug=slug,
    )


def _visible_invitation_token(card: _RawCard, source_url: str) -> str | None:
    values: set[str] = set()
    for href in (
        *(link.href for link in card.links),
        *(control.href for control in card.controls if control.href is not None),
    ):
        parsed = urlsplit(urljoin(source_url, href))
        for key in ("invitation", "contextEntityUrn"):
            for value in parse_qs(parsed.query).get(key, ()):
                if "invitation" in value.casefold():
                    values.add(value)
    if len(values) > 1:
        raise ParserDriftError("An invitation card exposes conflicting invitation identities.")
    return next(iter(values), None)


def _invitation_reference(
    *,
    direction: InvitationDirection,
    invitation_type: InvitationType,
    primary: _ParsedEntity,
    inviter: _ParsedEntity | None,
    visible_token: str | None,
) -> str:
    if primary.entity_type is InvitationEntityType.PERSON and primary.slug is not None:
        material = f"{direction.value}\x1f{primary.slug}"
    else:
        material = "\x1f".join(
            (
                direction.value,
                invitation_type.value,
                primary.entity_url or primary.display_name,
                inviter.entity_url if inviter is not None and inviter.entity_url else "",
                visible_token or "",
            )
        )
    return f"invitation:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _available_actions(card: _RawCard) -> tuple[InvitationAvailableAction, ...]:
    observed: set[InvitationAvailableAction] = set()
    for control in card.controls:
        value = control.label.casefold()
        text = control.text.casefold()
        if control.action == "accept":
            observed.add(InvitationAvailableAction.ACCEPT)
        elif control.action == "withdraw":
            observed.add(InvitationAvailableAction.WITHDRAW)
        elif value.startswith("ignore") or text == "ignore":
            observed.add(InvitationAvailableAction.IGNORE)
        elif value.startswith("reply") or text.startswith("reply"):
            observed.add(InvitationAvailableAction.REPLY)
        elif value.startswith("message") or value.startswith("send a message") or text == "message":
            observed.add(InvitationAvailableAction.MESSAGE)
    return tuple(action for action in InvitationAvailableAction if action in observed)


def _content_fields(
    card: _RawCard,
    *,
    primary_entity_type: InvitationEntityType,
    primary_name: str,
    inviter_name: str | None,
    selected_action: str,
) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    lines = _lines(card.visible_text)
    primary_control = next(
        control for control in card.controls if control.action == selected_action
    )
    action_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.casefold() == primary_control.text.casefold()
            or line.casefold() == selected_action
        ),
        len(lines),
    )
    excluded_names = {primary_name.casefold()}
    if inviter_name is not None:
        excluded_names.add(inviter_name.casefold())

    before: list[str] = []
    for line in lines[:action_index]:
        if line.casefold() in excluded_names or line in {"--", "Verified", "Premium"}:
            continue
        without_entities = line
        for name in (primary_name, inviter_name):
            if name is not None:
                without_entities = re.sub(
                    re.escape(name),
                    "",
                    without_entities,
                    flags=re.IGNORECASE,
                )
        without_entities = without_entities.strip(" \t\n\r,|-")
        if not without_entities or _ACTION_TEXT_PATTERN.match(without_entities):
            continue
        before.append(without_entities)
    relationship = next((line for line in before if _MUTUAL_PATTERN.search(line)), None)
    time_text = next((line for line in before if _TIME_PATTERN.search(line)), None)
    descriptive = [line for line in before if line not in {relationship, time_text}]
    if primary_entity_type is InvitationEntityType.PERSON:
        headline = descriptive[0] if descriptive else None
        context = "\n".join(descriptive[1:]) or None
    else:
        headline = None
        context = "\n".join(descriptive) or None

    explicit_note = card.explicit_note
    if explicit_note is not None:
        note = explicit_note
    else:
        after = [
            line
            for line in lines[action_index + 1 :]
            if line.casefold() not in excluded_names and not _ACTION_TEXT_PATTERN.match(line)
        ]
        note = "\n".join(after) or None
    return headline, context, note, time_text, relationship


def _parse_invitation(
    card: _RawCard,
    *,
    direction: InvitationDirection,
    source_url: str,
) -> _ParsedInvitation | None:
    selected_action = "accept" if direction is InvitationDirection.RECEIVED else "withdraw"
    primary_controls = [
        control for control in card.controls if control.action in {"accept", "withdraw", "connect"}
    ]
    selected_controls = [
        control for control in primary_controls if control.action == selected_action
    ]
    if not selected_controls:
        if len(primary_controls) == 1 and primary_controls[0].action == "connect":
            return None
        raise ParserDriftError(
            "A current invitation card has no action matching the selected direction."
        )
    if len(selected_controls) != 1 or any(
        control.action == "connect" for control in primary_controls
    ):
        raise ParserDriftError("An invitation card exposes ambiguous primary actions.")

    lines = _lines(card.visible_text)
    action_name = _action_target_name(card, selected_action)
    candidates = _entity_candidates(card, source_url=source_url)
    person_candidates = [
        (url, value) for url, value in candidates.items() if value[0] is InvitationEntityType.PERSON
    ]
    non_person_candidates = [
        (url, value)
        for url, value in candidates.items()
        if value[0] is not InvitationEntityType.PERSON
    ]

    inviter: _ParsedEntity | None = None
    if non_person_candidates:
        matching_targets = [
            candidate
            for candidate in non_person_candidates
            if action_name is not None
            and action_name.casefold() in {name.casefold() for name in candidate[1][2]}
        ]
        if len(non_person_candidates) == 1:
            primary_candidate = non_person_candidates[0]
        elif len(matching_targets) == 1:
            primary_candidate = matching_targets[0]
        else:
            raise ParserDriftError("An invitation card has an ambiguous non-person target.")
        primary_url, (primary_type, primary_slug, primary_names) = primary_candidate
        action_names_primary = action_name is not None and action_name.casefold() in {
            name.casefold() for name in primary_names
        }
        primary = _resolve_entity(
            entity_type=primary_type,
            slug=primary_slug,
            canonical_url=primary_url,
            names=primary_names,
            action_name=action_name,
            visible_lines=lines,
            prefer_action_name=action_names_primary,
        )
        remaining_candidates = [
            candidate
            for candidate in (*person_candidates, *non_person_candidates)
            if candidate[0] != primary_url
        ]
        if len(remaining_candidates) > 1:
            raise ParserDriftError("An invitation card has an ambiguous visible inviter.")
        if remaining_candidates:
            inviter_url, (inviter_type, inviter_slug, inviter_names) = remaining_candidates[0]
            action_names_inviter = action_name is not None and action_name.casefold() in {
                name.casefold() for name in inviter_names
            }
            inviter = _resolve_entity(
                entity_type=inviter_type,
                slug=inviter_slug,
                canonical_url=inviter_url,
                names=inviter_names,
                action_name=action_name,
                visible_lines=lines,
                prefer_action_name=action_names_inviter,
            )
    elif person_candidates:
        if len(person_candidates) != 1:
            raise ParserDriftError("An invitation card has an ambiguous member target.")
        primary_url, (primary_type, primary_slug, primary_names) = person_candidates[0]
        primary = _resolve_entity(
            entity_type=primary_type,
            slug=primary_slug,
            canonical_url=primary_url,
            names=primary_names,
            action_name=action_name,
            visible_lines=lines,
            prefer_action_name=True,
        )
    else:
        fallback_name = action_name or next(
            (
                line
                for line in lines
                if not _ACTION_TEXT_PATTERN.match(line)
                and not _MUTUAL_PATTERN.search(line)
                and not _TIME_PATTERN.search(line)
            ),
            None,
        )
        if fallback_name is None:
            raise ParserDriftError("An invitation card has no stable visible target identity.")
        primary = _ParsedEntity(
            entity_type=InvitationEntityType.OTHER,
            entity_url=None,
            display_name=fallback_name,
            slug=None,
        )

    invitation_type = _INVITATION_TYPE_BY_ENTITY[primary.entity_type]
    reference = _invitation_reference(
        direction=direction,
        invitation_type=invitation_type,
        primary=primary,
        inviter=inviter,
        visible_token=_visible_invitation_token(card, source_url),
    )
    headline, context, note, time_text, relationship = _content_fields(
        card,
        primary_entity_type=primary.entity_type,
        primary_name=primary.display_name,
        inviter_name=inviter.display_name if inviter is not None else None,
        selected_action=selected_action,
    )
    return _ParsedInvitation(
        invitation_ref=reference,
        direction=direction,
        invitation_type=invitation_type,
        primary_entity=primary,
        inviter=inviter,
        headline=headline,
        context=context,
        note=note,
        sent_or_received_at_text=time_text,
        relationship_context=relationship,
        available_actions=_available_actions(card),
        visible_text=card.visible_text,
    )


def _recommendation_signature(card: _RawCard) -> str:
    material = "\x1f".join(
        (
            card.visible_text,
            *(link.href for link in card.links),
            *(control.label for control in card.controls),
        )
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def _read_current_dom(
    page: Page,
    direction: InvitationDirection,
    *,
    allow_missing_column: bool = False,
) -> _DomObservation:
    mains = page.locator("main")
    if await mains.count() != 1:
        raise ParserDriftError("LinkedIn Invitations has no unique current main surface.")
    main = mains.first
    raw = await main.evaluate(
        """
        (element, options) => {
          const visible = candidate => candidate.getClientRects().length > 0;
          const labelOf = control => (
            control.getAttribute("aria-label") || control.innerText || ""
          ).trim();
          const actionOf = control => {
            const value = labelOf(control);
            if (/^accept(?:\\s|$)/i.test(value)) return "accept";
            if (/^withdraw(?:\\s|$)/i.test(value)) return "withdraw";
            if (/^connect(?:\\s|$)/i.test(value)) return "connect";
            return null;
          };
          const columns = Array.from(
            element.querySelectorAll('[data-testid="lazy-column"]')
          ).filter(visible);
          if (columns.length === 0 && options.allowMissingColumn) {
            return {
              cards: [],
              columnCount: 0,
              invalidCardCount: 0,
              totalRoots: 0,
              unmatchedPrimaryCount: 0
            };
          }
          if (columns.length !== 1) {
            return {
              cards: [],
              columnCount: columns.length,
              invalidCardCount: 0,
              totalRoots: 0,
              unmatchedPrimaryCount: 0
            };
          }
          const column = columns[0];
          const selector = options.direction === "received"
            ? ':scope [data-display-contents] > [role="listitem"]'
            : ':scope > [role="listitem"]';
          const roots = Array.from(column.querySelectorAll(selector)).filter(visible);
          const rootSet = new Set(roots);
          const primaryControls = Array.from(
            column.querySelectorAll("button,a")
          ).filter(control => visible(control) && actionOf(control) !== null);
          const unmatchedPrimaryCount = primaryControls.filter(control => {
            const containingRoots = roots.filter(root => root.contains(control));
            return containingRoots.length !== 1;
          }).length;
          let invalidCardCount = 0;
          const cards = [];
          for (const root of roots) {
            const primary = Array.from(root.querySelectorAll("button,a"))
              .filter(control => visible(control) && actionOf(control) !== null);
            if (primary.length === 0) continue;
            const selected = primary.filter(control => (
              actionOf(control) === (
                options.direction === "received" ? "accept" : "withdraw"
              )
            ));
            const connect = primary.filter(control => actionOf(control) === "connect");
            if (!(
              (selected.length === 1 && connect.length === 0) ||
              (selected.length === 0 && connect.length === 1 && primary.length === 1)
            )) {
              invalidCardCount += 1;
            }
            const note = root.querySelector(
              '[class*="invitation-card__custom-message"],' +
              '[class*="invitation-card__message"],' +
              '[data-test-invitation-message]'
            );
            cards.push({
              visible_text: root.innerText?.trim() ?? "",
              explicit_note: note?.innerText?.trim() ?? null,
              links: Array.from(root.querySelectorAll("a[href]"))
                .filter(visible)
                .slice(0, 50)
                .map(link => ({
                  href: link.getAttribute("href") ?? "",
                  text: link.innerText?.trim() ?? "",
                  aria_label: link.getAttribute("aria-label"),
                  image_alts: Array.from(link.querySelectorAll("img"))
                    .map(image => image.getAttribute("alt") || "")
                    .filter(Boolean)
                    .slice(0, 10)
                })),
              controls: Array.from(root.querySelectorAll("button,a"))
                .filter(visible)
                .slice(0, 50)
                .map(control => ({
                  label: labelOf(control),
                  text: control.innerText?.trim() ?? "",
                  href: control.getAttribute("href"),
                  action: actionOf(control)
                }))
            });
          }
          return {
            cards: cards.slice(0, options.limit),
            columnCount: 1,
            invalidCardCount,
            totalRoots: cards.length,
            unmatchedPrimaryCount
          };
        }
        """,
        {
            "allowMissingColumn": allow_missing_column,
            "direction": direction.value,
            "limit": _MAX_RAW_CARDS,
        },
    )
    if not isinstance(raw, dict):
        raise ParserDriftError("LinkedIn Invitations returned invalid card diagnostics.")
    result = cast(dict[str, object], raw)
    column_count = result.get("columnCount")
    total_roots = result.get("totalRoots")
    invalid_count = result.get("invalidCardCount")
    unmatched_count = result.get("unmatchedPrimaryCount")
    raw_cards = result.get("cards")
    if not all(
        isinstance(value, int)
        for value in (column_count, total_roots, invalid_count, unmatched_count)
    ) or not isinstance(raw_cards, list):
        raise ParserDriftError("LinkedIn Invitations returned incomplete card diagnostics.")
    if cast(int, column_count) == 0 and allow_missing_column:
        return _DomObservation(cards=(), signature=())
    if cast(int, column_count) != 1:
        raise ParserDriftError("LinkedIn Invitations has no unique current lazy-column.")
    if cast(int, total_roots) > _MAX_RAW_CARDS:
        raise ParserDriftError("LinkedIn rendered more invitation cards than the parser bound.")
    if cast(int, invalid_count) or cast(int, unmatched_count):
        raise ParserDriftError(
            "LinkedIn Invitations no longer matches the current exact card-root contract."
        )
    cards = tuple(
        card for value in cast(list[object], raw_cards) if (card := _raw_card(value)) is not None
    )
    if len(cards) != len(cast(list[object], raw_cards)):
        raise ParserDriftError("A current invitation card has an invalid DOM projection.")
    signatures = tuple(
        hashlib.sha256(
            "\x1f".join(
                (
                    card.visible_text,
                    *(link.href for link in card.links),
                    *(control.label for control in card.controls),
                )
            ).encode()
        ).hexdigest()
        for card in cards
    )
    return _DomObservation(cards=cards, signature=signatures)


async def _read_dom_signature(
    page: Page,
    direction: InvitationDirection,
    allow_missing_column: bool,
) -> tuple[str, ...]:
    return (
        await _read_current_dom(
            page,
            direction,
            allow_missing_column=allow_missing_column,
        )
    ).signature


async def _visible_inventory(
    page: Page,
    invitation_filter: InvitationFilter,
) -> _VisibleInventory:
    if invitation_filter is InvitationFilter.ALL:
        raise ValueError("The synthetic All filter has no single visible inventory control.")
    pattern = _COUNT_PATTERNS[invitation_filter]
    mains = page.locator("main")
    if await mains.count() != 1:
        raise ParserDriftError("LinkedIn Invitations has no unique current main surface.")
    raw = await mains.first.evaluate(
        """
        (element, options) => {
          const visible = candidate => candidate.getClientRects().length > 0;
          return Array.from(
            element.querySelectorAll('[role="button"],[role="radio"],a[href]')
          )
            .filter(visible)
            .slice(0, 100)
            .map(control => {
              const checkbox = control.querySelector('input[type="checkbox"]');
              return {
                label: (
                  control.getAttribute("aria-label") || control.innerText || ""
                ).trim(),
                tag: control.tagName,
                role: control.getAttribute("role"),
                href: control.getAttribute("href"),
                selected: (
                  control.getAttribute("aria-checked") === "true" ||
                  control.getAttribute("aria-selected") === "true" ||
                  control.getAttribute("aria-pressed") === "true" ||
                  checkbox?.checked === true
                )
              };
            });
        }
        """,
        {"invitationFilter": invitation_filter.value},
    )
    if not isinstance(raw, list):
        raise ParserDriftError("LinkedIn Invitations returned invalid filter diagnostics.")
    matches: list[_VisibleInventory] = []
    for value in cast(list[object], raw):
        if not isinstance(value, dict):
            continue
        control = cast(dict[str, object], value)
        label = control.get("label")
        tag = control.get("tag")
        role = control.get("role")
        href = control.get("href")
        selected = control.get("selected")
        if (
            not isinstance(label, str)
            or not isinstance(tag, str)
            or not (isinstance(role, str) or role is None)
            or not (isinstance(href, str) or href is None)
            or not isinstance(selected, bool)
        ):
            continue
        match = pattern.fullmatch(label)
        if match is None:
            continue
        if invitation_filter is InvitationFilter.PEOPLE and tag == "A":
            if href is None:
                continue
            path = urlsplit(urljoin(page.url, href)).path.rstrip("/")
            if path != _SENT_PEOPLE_PATH:
                raise ParserDriftError(
                    "LinkedIn Invitations exposed an unexpected People filter target."
                )
            matches.append(
                _VisibleInventory(
                    invitation_filter=invitation_filter,
                    count=int(match.group("count").replace(",", "")),
                    label=label,
                )
            )
            continue
        expected_roles = (
            {"button"}
            if invitation_filter in _BUCKET_FILTERS
            else {"radio"}
            if invitation_filter in _CATEGORY_FILTERS
            else {"button", "radio"}
        )
        if role not in expected_roles:
            continue
        if selected or (invitation_filter is InvitationFilter.PEOPLE and role == "button"):
            matches.append(
                _VisibleInventory(
                    invitation_filter=invitation_filter,
                    count=int(match.group("count").replace(",", "")),
                    label=label,
                )
            )
    if len(matches) != 1:
        raise ParserDriftError(
            "LinkedIn Invitations has no unique advertised count for the selected view."
        )
    return matches[0]


async def _wait_for_inventory(
    page: Page,
    invitation_filter: InvitationFilter,
) -> _VisibleInventory:
    last_error: ParserDriftError | None = None
    for _ in range(_INVENTORY_ATTEMPTS):
        try:
            return await _visible_inventory(page, invitation_filter)
        except ParserDriftError as error:
            last_error = error
            await page.wait_for_timeout(_INVENTORY_DELAY_MS)
    assert last_error is not None
    raise last_error


async def _unique_visible_role_control(
    page: Page,
    *,
    role: Literal["button", "link", "menuitem", "radio"],
    name: re.Pattern[str],
    description: str,
) -> Locator:
    visible = await _visible_role_controls(page, role=role, name=name)
    if len(visible) != 1:
        raise ParserDriftError(f"LinkedIn Invitations has no unique current {description} control.")
    return visible[0]


async def _visible_role_controls(
    page: Page,
    *,
    role: Literal["button", "link", "menuitem", "radio"],
    name: re.Pattern[str],
) -> tuple[Locator, ...]:
    controls = page.get_by_role(role, name=name)
    visible: list[Locator] = []
    for index in range(await controls.count()):
        control = controls.nth(index)
        if await control.is_visible():
            visible.append(control)
    return tuple(visible)


async def _has_visible_filter_shape(
    page: Page,
    invitation_filter: InvitationFilter,
) -> bool:
    mains = page.locator("main")
    if await mains.count() != 1:
        raise ParserDriftError("LinkedIn Invitations has no unique current main surface.")
    pattern = _CONTROL_OMISSION_GUARD_PATTERNS[invitation_filter]
    for role in ("button", "link", "menuitem", "radio"):
        controls = mains.first.get_by_role(role, name=pattern)
        for index in range(await controls.count()):
            if await controls.nth(index).is_visible():
                return True
    return False


async def _implicit_category_empty_inventory(
    page: Page,
    invitation_filter: InvitationFilter,
) -> _VisibleInventory:
    if invitation_filter not in _CATEGORY_FILTERS:
        raise ValueError("Only current received category views may use omission-as-zero.")
    if await _has_visible_filter_shape(page, invitation_filter):
        raise ParserDriftError(
            f"LinkedIn Invitations exposed a changed {invitation_filter.value} filter shape."
        )
    focused = await _visible_inventory(page, InvitationFilter.FOCUSED)
    return _VisibleInventory(
        invitation_filter=invitation_filter,
        count=0,
        label=focused.label,
        advertised=False,
    )


async def _read_implicit_sent_empty_evidence(page: Page) -> str | None:
    path = urlsplit(page.url).path.rstrip("/")
    if path not in {_SENT_ROOT_PATH, _SENT_PEOPLE_PATH}:
        raise ParserDriftError("LinkedIn Invitations exposed an unexpected empty Sent target.")
    if await _has_visible_filter_shape(page, InvitationFilter.PEOPLE):
        raise ParserDriftError("LinkedIn Invitations exposed a changed People filter shape.")
    mains = page.locator("main")
    if await mains.count() != 1:
        raise ParserDriftError("LinkedIn Invitations has no unique current main surface.")
    raw = await mains.first.evaluate(
        """
        element => {
          const visible = candidate => candidate.getClientRects().length > 0;
          const labelOf = control => (
            control.getAttribute("aria-label") || control.innerText || ""
          ).trim();
          const columns = Array.from(
            element.querySelectorAll('[data-testid="lazy-column"]')
          ).filter(visible);
          const roots = columns.flatMap(column =>
            Array.from(column.querySelectorAll(':scope > [role="listitem"]')).filter(visible)
          );
          const controls = Array.from(element.querySelectorAll("button,a")).filter(visible);
          const lines = (element.innerText || "")
            .split(/\\n+/)
            .map(line => line.trim())
            .filter(Boolean);
          return {
            busy: (
              element.getAttribute("aria-busy") === "true" ||
              Boolean(element.querySelector('[aria-busy="true"]'))
            ),
            columnCount: columns.length,
            rootCount: roots.length,
            withdrawalCount: controls.filter(control =>
              /^withdraw(?:\\s|$)/i.test(labelOf(control))
            ).length,
            loadMoreCount: controls.filter(control =>
              /^(?:load more|show more(?: results)?|see more)$/i.test(labelOf(control))
            ).length,
            headingCount: lines.filter(line => line === "Manage invitations").length
          };
        }
        """
    )
    if not isinstance(raw, dict):
        raise ParserDriftError("LinkedIn Invitations returned invalid empty Sent diagnostics.")
    result = cast(dict[str, object], raw)
    if result.get("busy") is True or result.get("loadMoreCount") != 0:
        return None
    if (
        result.get("columnCount") != 1
        or result.get("rootCount") != 0
        or result.get("withdrawalCount") != 0
        or result.get("headingCount") != 1
    ):
        raise ParserDriftError(
            "LinkedIn Invitations cannot prove the current omitted People view empty."
        )
    return "Manage invitations"


async def _implicit_sent_empty_inventory(page: Page) -> _VisibleInventory:
    stable_rounds = 0
    evidence: str | None = None
    for attempt_index in range(_SETTLE_ATTEMPTS):
        if attempt_index:
            await page.wait_for_timeout(_SETTLE_DELAY_MS)
        try:
            advertised = await _visible_inventory(page, InvitationFilter.PEOPLE)
        except ParserDriftError:
            advertised = None
        if advertised is not None:
            return advertised
        current_evidence = await _read_implicit_sent_empty_evidence(page)
        if current_evidence is None:
            stable_rounds = 0
            evidence = None
        else:
            evidence = current_evidence
            stable_rounds += 1
    if evidence is not None and stable_rounds >= 2:
        return _VisibleInventory(
            invitation_filter=InvitationFilter.PEOPLE,
            count=0,
            label=evidence,
            advertised=False,
        )
    raise ParserDriftError("LinkedIn Invitations did not establish stable empty Sent evidence.")


async def _select_visible_view(
    page: Page,
    browser: BrowserManager,
    direction: InvitationDirection,
    invitation_filter: InvitationFilter,
) -> _VisibleInventory:
    try:
        return await _visible_inventory(page, invitation_filter)
    except ParserDriftError:
        pass

    try:
        baseline = (
            await _read_current_dom(
                page,
                direction,
                allow_missing_column=True,
            )
        ).signature
    except ParserDriftError:
        baseline = ()

    if invitation_filter in _BUCKET_FILTERS:
        picker = await _unique_visible_role_control(
            page,
            role="button",
            name=_BUCKET_PICKER_PATTERN,
            description="Focused/Other selector",
        )
        await browser.click_visible_control(page, picker)
        option = await _unique_visible_role_control(
            page,
            role="menuitem",
            name=_CONTROL_NAME_PATTERNS[invitation_filter],
            description=f"{invitation_filter.value} menu option",
        )
        await browser.click_visible_control(page, option)
    elif invitation_filter in _CATEGORY_FILTERS:
        try:
            control = await _unique_visible_role_control(
                page,
                role="radio",
                name=_CONTROL_NAME_PATTERNS[invitation_filter],
                description=f"{invitation_filter.value} filter",
            )
        except ParserDriftError:
            # The current UI hides every category radio while Other is active.
            # Returning through the visible Focused picker restores them.
            await _select_visible_view(
                page,
                browser,
                direction,
                InvitationFilter.FOCUSED,
            )
            category_controls = await _visible_role_controls(
                page,
                role="radio",
                name=_CONTROL_NAME_PATTERNS[invitation_filter],
            )
            if not category_controls:
                return await _implicit_category_empty_inventory(page, invitation_filter)
            if len(category_controls) != 1:
                raise ParserDriftError(
                    "LinkedIn Invitations has no unique current "
                    f"{invitation_filter.value} filter control."
                ) from None
            control = category_controls[0]
        await browser.click_visible_control(page, control)
    elif invitation_filter is InvitationFilter.PEOPLE:
        controls: list[Locator] = []
        for role in ("link", "radio", "button"):
            controls.extend(
                await _visible_role_controls(
                    page,
                    role=role,
                    name=_CONTROL_NAME_PATTERNS[invitation_filter],
                )
            )
        if not controls:
            return await _implicit_sent_empty_inventory(page)
        if len(controls) != 1:
            raise ParserDriftError(
                "LinkedIn Invitations has no unique current People filter control."
            )
        await browser.click_visible_control(page, controls[0])
    else:
        raise ValueError("The synthetic All filter cannot be selected directly.")
    inventory = await _wait_for_inventory(page, invitation_filter)
    await wait_for_collection_change(
        page,
        baseline=baseline,
        read_signature=lambda: _read_dom_signature(
            page,
            direction,
            inventory.count == 0,
        ),
        attempts=_SETTLE_ATTEMPTS,
        delay_ms=_SETTLE_DELAY_MS,
    )
    return inventory


async def _unique_load_more(page: Page) -> Locator | None:
    candidates: list[Locator] = []
    for role in ("button", "link"):
        controls = page.get_by_role(role, name=_LOAD_MORE_PATTERN)
        for index in range(await controls.count()):
            control = controls.nth(index)
            if await control.is_visible():
                candidates.append(control)
    if len(candidates) > 1:
        raise ParserDriftError("LinkedIn Invitations exposed ambiguous Load more controls.")
    return candidates[0] if candidates else None


class InvitationListPage:
    """Collect one bounded live invitation prefix from the current UI."""

    def __init__(
        self,
        browser: BrowserManager,
        *,
        max_scroll_rounds: int,
    ) -> None:
        if max_scroll_rounds < 1:
            raise ValueError("Invitation collection requires a positive scroll bound.")
        self._browser = browser
        self._max_scroll_rounds = max_scroll_rounds

    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: InvitationProgressReporter | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Invitation collection requires a positive result limit.")
        navigation_url = _NAVIGATION_URLS[request.direction]
        for attempt_index in range(2):
            try:
                return await self._collect_attempt(
                    request,
                    navigation_url=navigation_url,
                    attempt_index=attempt_index,
                    result_limit=limit,
                    progress=progress,
                )
            except _CollectionChanged:
                if attempt_index == 0:
                    continue
                raise BrowserUnavailableError(
                    "LinkedIn invitation counts changed repeatedly during collection; retry."
                ) from None
        raise AssertionError("The bounded invitation collection attempt loop did not terminate.")

    async def _collect_attempt(
        self,
        request: InvitationListInput,
        *,
        navigation_url: str,
        attempt_index: int,
        result_limit: int,
        progress: InvitationProgressReporter | None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
        selected = request.resolved_filter
        views = (
            CURRENT_RECEIVED_INVITATION_VIEWS
            if request.direction is InvitationDirection.RECEIVED
            and selected is InvitationFilter.ALL
            else (selected,)
        )
        captured: dict[str, _CapturedInvitation] = {}
        view_source_urls: dict[InvitationFilter, str] = {}
        recommendations: set[str] = set()
        scroll_rounds = 0
        observed_view_memberships = 0
        completed_views = 0
        stop_reason = StopReason.VISIBLE_PAGE_COMPLETE
        async with self._browser.page() as page:
            await self._browser.navigate(page, navigation_url)
            mains = page.locator("main")
            if await mains.count() != 1:
                raise ParserDriftError("LinkedIn Invitations has no unique current main surface.")
            await mains.first.wait_for(state="visible")
            inventories: dict[InvitationFilter, _VisibleInventory] = {}
            for invitation_filter in views:
                inventories[invitation_filter] = await _select_visible_view(
                    page,
                    self._browser,
                    request.direction,
                    invitation_filter,
                )
                view_source_urls[invitation_filter] = page.url
            view_membership_count = sum(inventory.count for inventory in inventories.values())
            if progress is not None:
                await progress(
                    0,
                    view_membership_count,
                    (f"Selected invitation views advertise {view_membership_count} memberships"),
                )

            progress_offset = 0
            for view_index, invitation_filter in enumerate(views):
                inventory = await _select_visible_view(
                    page,
                    self._browser,
                    request.direction,
                    invitation_filter,
                )
                expected = inventories[invitation_filter]
                if inventory != expected:
                    raise _CollectionChanged
                view_source_urls[invitation_filter] = page.url
                if not expected.advertised:
                    if expected.count != 0:
                        raise ParserDriftError(
                            "An unadvertised invitation view cannot have visible members."
                        )
                    completed_views += 1
                    continue
                (
                    view_items,
                    view_recommendations,
                    view_rounds,
                    view_stop_reason,
                ) = await self._collect_view(
                    page,
                    direction=request.direction,
                    inventory=expected,
                    source_url=page.url,
                    prior_invitation_refs=frozenset(captured),
                    result_limit=result_limit,
                    progress=progress,
                    progress_offset=progress_offset,
                    progress_total=view_membership_count,
                    max_scroll_rounds=self._max_scroll_rounds - scroll_rounds,
                )
                for invitation_ref, item in view_items.items():
                    existing = captured.get(invitation_ref)
                    if existing is not None and existing.invitation != item.invitation:
                        raise ParserDriftError(
                            "The same stable invitation exposes conflicting data across "
                            "LinkedIn's current visible views."
                        )
                    captured.setdefault(invitation_ref, item)
                recommendations.update(view_recommendations)
                observed_view_memberships += len(view_items)
                scroll_rounds += view_rounds
                progress_offset += expected.count
                if view_stop_reason is not StopReason.VISIBLE_PAGE_COMPLETE:
                    stop_reason = view_stop_reason
                    break
                completed_views += 1
                if len(captured) >= result_limit and view_index + 1 < len(views):
                    stop_reason = StopReason.RESULT_LIMIT
                    break

            for invitation_filter, expected in inventories.items():
                current = await _select_visible_view(
                    page,
                    self._browser,
                    request.direction,
                    invitation_filter,
                )
                if current != expected:
                    raise _CollectionChanged

            if completed_views == len(views):
                stop_reason = StopReason.VISIBLE_PAGE_COMPLETE
            captured_at = datetime.now(UTC)
            invitations = tuple(
                item.invitation.public(
                    source_url=item.source_url,
                    captured_at=captured_at,
                )
                for item in captured.values()
            )
            type_counts: dict[InvitationType, int] = {}
            entity_counts: dict[InvitationEntityType, int] = {}
            for invitation in invitations:
                type_counts[invitation.invitation_type] = (
                    type_counts.get(invitation.invitation_type, 0) + 1
                )
                entity_type = invitation.primary_entity.entity_type
                entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
            coverage = InvitationListCoverage(
                direction=request.direction,
                invitation_filter=selected,
                advertised_count=(
                    None
                    if selected is InvitationFilter.ALL or not inventories[selected].advertised
                    else inventories[selected].count
                ),
                unique_count=len(invitations),
                view_counts={
                    invitation_filter: inventory.count
                    for invitation_filter, inventory in inventories.items()
                },
                unadvertised_empty_views=tuple(
                    invitation_filter
                    for invitation_filter, inventory in inventories.items()
                    if not inventory.advertised
                ),
                view_source_urls={
                    invitation_filter: HttpUrl(source_url)
                    for invitation_filter, source_url in view_source_urls.items()
                },
                view_membership_count=view_membership_count,
                overlap_count=observed_view_memberships - len(invitations),
                result_count=len(invitations),
                max_results=result_limit,
                scroll_rounds=scroll_rounds,
                collection_attempts=attempt_index + 1,
                neighboring_recommendation_count=len(recommendations),
                invitation_type_counts=type_counts,
                entity_type_counts=entity_counts,
                stop_reason=stop_reason,
                captured_at=captured_at,
            )
            advertised_label = "\n".join(
                dict.fromkeys(inventory.label for inventory in inventories.values())
            )
            captured_text = "\n\n".join(
                (advertised_label, *(item.visible_text for item in invitations))
            )
            return invitations, coverage, captured_text, navigation_url

    async def _collect_view(
        self,
        page: Page,
        *,
        direction: InvitationDirection,
        inventory: _VisibleInventory,
        source_url: str,
        prior_invitation_refs: frozenset[str],
        result_limit: int,
        progress: InvitationProgressReporter | None,
        progress_offset: int,
        progress_total: int,
        max_scroll_rounds: int,
    ) -> tuple[dict[str, _CapturedInvitation], set[str], int, StopReason]:
        parsed: dict[str, _CapturedInvitation] = {}
        recommendations: set[str] = set()
        scroll_rounds = 0
        for round_index in range(max_scroll_rounds + 1):
            current = await _visible_inventory(page, inventory.invitation_filter)
            if current != inventory:
                raise _CollectionChanged
            observation = await _read_current_dom(
                page,
                direction,
                allow_missing_column=inventory.count == 0,
            )
            visible_invitations: dict[str, _CapturedInvitation] = {}
            for card in observation.cards:
                invitation = _parse_invitation(
                    card,
                    direction=direction,
                    source_url=page.url,
                )
                if invitation is None:
                    recommendations.add(_recommendation_signature(card))
                    continue
                captured = _CapturedInvitation(invitation=invitation, source_url=source_url)
                visible_copy = visible_invitations.get(invitation.invitation_ref)
                if visible_copy is not None:
                    if visible_copy != captured:
                        raise ParserDriftError(
                            "Duplicate invitation renders expose conflicting visible data."
                        )
                    continue
                visible_invitations[invitation.invitation_ref] = captured
                existing = parsed.get(invitation.invitation_ref)
                if existing is not None and existing != captured:
                    raise ParserDriftError(
                        "A stable invitation identity rendered conflicting visible data."
                    )
                parsed.setdefault(invitation.invitation_ref, captured)
            if len(parsed) > inventory.count:
                raise ParserDriftError(
                    "Parsed invitations exceed LinkedIn's advertised selected-view count."
                )
            if progress is not None:
                await progress(
                    progress_offset + len(parsed),
                    progress_total,
                    (f"Parsed {progress_offset + len(parsed)} of {progress_total} invitations"),
                )
            observed_refs = prior_invitation_refs.union(parsed)
            if len(observed_refs) >= result_limit:
                bounded: dict[str, _CapturedInvitation] = {}
                bounded_refs = set(prior_invitation_refs)
                for invitation_ref, invitation in parsed.items():
                    bounded[invitation_ref] = invitation
                    bounded_refs.add(invitation_ref)
                    if len(bounded_refs) >= result_limit:
                        break
                if len(parsed) == inventory.count and len(bounded) == len(parsed):
                    return (
                        bounded,
                        recommendations,
                        scroll_rounds,
                        StopReason.VISIBLE_PAGE_COMPLETE,
                    )
                return bounded, recommendations, scroll_rounds, StopReason.RESULT_LIMIT
            if len(parsed) == inventory.count:
                return (
                    parsed,
                    recommendations,
                    scroll_rounds,
                    StopReason.VISIBLE_PAGE_COMPLETE,
                )
            if round_index >= max_scroll_rounds:
                break

            load_more = await _unique_load_more(page)
            baseline = observation.signature
            if load_more is not None:
                await self._browser.click_visible_control(page, load_more)
            else:
                mains = page.locator("main")
                if await mains.count() != 1:
                    raise ParserDriftError(
                        "LinkedIn Invitations has no unique current main surface."
                    )
                await mains.first.hover()
                await page.mouse.wheel(0, _SCROLL_DELTA)
            scroll_rounds += 1
            await wait_for_collection_change(
                page,
                baseline=baseline,
                read_signature=lambda: _read_dom_signature(
                    page,
                    direction,
                    inventory.count == 0,
                ),
                attempts=_SETTLE_ATTEMPTS,
                delay_ms=_SETTLE_DELAY_MS,
            )

        return parsed, recommendations, scroll_rounds, StopReason.SAFETY_BOUND
