"""Shared lexical contracts for public LinkedIn identifiers."""

PROFILE_SLUG_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{2,199}"
PROFILE_SLUG_PATTERN = rf"^{PROFILE_SLUG_SEGMENT_PATTERN}$"
