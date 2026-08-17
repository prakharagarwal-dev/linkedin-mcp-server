from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    ProfileSlug,
    StrictModel,
)


class PostMentionInput(StrictModel):
    token: Annotated[
        str,
        Field(
            min_length=2,
            max_length=500,
            description=(
                "Exact, unique @mention token in the post text. The visible picker must "
                "resolve it to the supplied member or company identity."
            ),
        ),
    ]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostMentionInput:
        if not self.token.startswith("@"):
            raise ValueError("A post mention token must begin with @")
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("A post mention requires exactly one member or company identity")
        return self
