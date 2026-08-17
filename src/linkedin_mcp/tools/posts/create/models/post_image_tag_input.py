from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    ProfileSlug,
    StrictModel,
)


class PostImageTagInput(StrictModel):
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None

    @model_validator(mode="after")
    def require_one_identity(self) -> PostImageTagInput:
        if (self.profile_slug is None) == (self.company_slug is None):
            raise ValueError("An image tag requires exactly one member or company identity")
        return self
