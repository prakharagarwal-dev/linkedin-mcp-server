"""LinkedIn post and comment reference parsing and URL construction."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from linkedin_mcp.errors import InvalidTargetError

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
