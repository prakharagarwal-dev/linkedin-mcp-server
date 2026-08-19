"""Canonical LinkedIn URL construction and validation."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from linkedin_mcp.errors import InvalidTargetError

PROFILE_SLUG_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{2,199}"
PROFILE_SLUG_PATTERN = rf"^{PROFILE_SLUG_SEGMENT_PATTERN}$"

_JOB_PATH = re.compile(r"^/jobs/view/(?P<job_id>[0-9]{5,30})(?:/|$)")
_PROFILE_PATH = re.compile(rf"^/in/(?P<profile_slug>{PROFILE_SLUG_SEGMENT_PATTERN})(?:/|$)")
_COMPANY_PATH = re.compile(
    r"^/company/(?P<company_slug>[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?)"
    r"(?:/|$)"
)
_CONVERSATION_PATH = re.compile(
    r"^/messaging/thread/(?P<conversation_id>[A-Za-z0-9_%=-]{3,500})(?:/|$)"
)
_POST_URN = re.compile(r"urn:li:(?P<kind>activity|share|ugcPost):(?P<id>[0-9]{5,30})")
_POST_REFERENCE = re.compile(r"^(?P<kind>activity|share|ugc-post):(?P<id>[0-9]{5,30})$")
_POST_ACTIVITY_PATH = re.compile(r"(?:^|[-/_])activity-(?P<id>[0-9]{5,30})(?:[-/?]|$)")
_POST_UGC_PATH = re.compile(
    r"(?:^|[-/_])ugc-?post-(?P<id>[0-9]{5,30})(?:[-/?]|$)",
    re.IGNORECASE,
)
_POST_SHARE_PATH = re.compile(r"(?:^|[-/_])share-(?P<id>[0-9]{5,30})(?:[-/?]|$)")
_COMMENT_URN = re.compile(
    r"urn:li:comment:\((?:urn:li:)?"
    r"(?P<kind>activity|share|ugcPost):(?P<post_id>[0-9]{5,30}),"
    r"(?P<comment_id>[0-9]{1,30})\)"
)
_COMMENT_REFERENCE = re.compile(
    r"^comment:(?P<kind>activity|share|ugc-post):(?P<post_id>[0-9]{5,30}):"
    r"(?P<comment_id>[0-9]{1,30})$"
)


def validate_linkedin_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in allowed_hosts:
        raise InvalidTargetError("LinkedIn targets must use HTTPS and an allowed exact host.")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise InvalidTargetError("LinkedIn targets cannot contain credentials or custom ports.")
    return urlunsplit(("https", host, parsed.path, parsed.query, ""))


def job_id_from_url(url: str) -> str | None:
    parsed = urlsplit(url)
    path_match = _JOB_PATH.match(parsed.path)
    if path_match:
        return path_match.group("job_id")
    query = parse_qs(parsed.query)
    current_job_id = query.get("currentJobId", [None])[0]
    if current_job_id and re.fullmatch(r"[0-9]{5,30}", current_job_id):
        return current_job_id
    return None


def canonical_job_url(job_id: str) -> str:
    if not re.fullmatch(r"[0-9]{5,30}", job_id):
        raise InvalidTargetError("LinkedIn job IDs must contain 5 to 30 digits.")
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


def profile_slug_from_url(url: str) -> str | None:
    match = _PROFILE_PATH.match(urlsplit(url).path)
    return match.group("profile_slug") if match else None


def canonical_profile_url(profile_slug: str) -> str:
    if not re.fullmatch(PROFILE_SLUG_PATTERN, profile_slug):
        raise InvalidTargetError(
            "LinkedIn profile slugs must contain 3 to 200 letters, digits, or hyphens."
        )
    return f"https://www.linkedin.com/in/{profile_slug}/"


def company_slug_from_url(url: str) -> str | None:
    match = _COMPANY_PATH.match(urlsplit(url).path)
    return match.group("company_slug") if match else None


def canonical_company_url(company_slug: str, section: str | None = None) -> str:
    if not re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?",
        company_slug,
    ):
        raise InvalidTargetError(
            "LinkedIn company slugs must contain 1 to 200 letters, digits, or hyphens."
        )
    suffix = ""
    if section is not None:
        if section != "about":
            raise InvalidTargetError("The requested LinkedIn company section is unsupported.")
        suffix = f"{section}/"
    return f"https://www.linkedin.com/company/{company_slug}/{suffix}"


def post_reference_from_value(value: str) -> str | None:
    urn_match = _POST_URN.search(value)
    if urn_match:
        raw_kind = urn_match.group("kind")
        kind = "ugc-post" if raw_kind == "ugcPost" else raw_kind
        return f"{kind}:{urn_match.group('id')}"
    activity_match = _POST_ACTIVITY_PATH.search(urlsplit(value).path)
    if activity_match:
        return f"activity:{activity_match.group('id')}"
    ugc_match = _POST_UGC_PATH.search(urlsplit(value).path)
    if ugc_match:
        return f"ugc-post:{ugc_match.group('id')}"
    share_match = _POST_SHARE_PATH.search(urlsplit(value).path)
    if share_match:
        return f"share:{share_match.group('id')}"
    reference_match = _POST_REFERENCE.fullmatch(value)
    return reference_match.group(0) if reference_match else None


def canonical_post_url(post_ref: str) -> str:
    match = _POST_REFERENCE.fullmatch(post_ref)
    if match is None:
        raise InvalidTargetError(
            "LinkedIn post references must be activity:<digits>, share:<digits>, "
            "or ugc-post:<digits>."
        )
    kind = match.group("kind")
    urn_kind = "ugcPost" if kind == "ugc-post" else kind
    return f"https://www.linkedin.com/feed/update/urn:li:{urn_kind}:{match.group('id')}/"


def comment_reference_from_value(value: str) -> str | None:
    urn_match = _COMMENT_URN.search(value)
    if urn_match:
        raw_kind = urn_match.group("kind")
        kind = "ugc-post" if raw_kind == "ugcPost" else raw_kind
        return f"comment:{kind}:{urn_match.group('post_id')}:{urn_match.group('comment_id')}"
    reference_match = _COMMENT_REFERENCE.fullmatch(value)
    return reference_match.group(0) if reference_match else None


def post_reference_from_comment_ref(comment_ref: str) -> str:
    match = _COMMENT_REFERENCE.fullmatch(comment_ref)
    if match is None:
        raise InvalidTargetError("The LinkedIn comment reference is invalid.")
    return f"{match.group('kind')}:{match.group('post_id')}"


def conversation_id_from_url(url: str) -> str | None:
    match = _CONVERSATION_PATH.match(urlsplit(url).path)
    return match.group("conversation_id") if match else None


def canonical_conversation_url(conversation_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_%=-]{3,500}", conversation_id):
        raise InvalidTargetError(
            "LinkedIn conversation IDs must be one safe visible messaging path segment."
        )
    return f"https://www.linkedin.com/messaging/thread/{conversation_id}/"
