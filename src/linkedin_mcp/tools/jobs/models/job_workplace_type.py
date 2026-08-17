from __future__ import annotations

from enum import StrEnum


class JobWorkplaceType(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    HYBRID = "hybrid"
