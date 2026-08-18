from __future__ import annotations

from datetime import datetime
from typing import Literal

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class CompanyProfileCoverage(StrictModel):
    pages_visited: Literal[2] = 2
    returned_sections: tuple[Literal["overview"], Literal["about"]] = (
        "overview",
        "about",
    )
    captured_at: datetime
