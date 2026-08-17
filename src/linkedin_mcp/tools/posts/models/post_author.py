from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    CompanySlug,
    ProfileSlug,
    StrictModel,
)
from linkedin_mcp.tools.posts.get.models.post_author_type import PostAuthorType


class PostAuthor(StrictModel):
    author_type: PostAuthorType
    name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: ProfileSlug | None = None
    company_slug: CompanySlug | None = None
    author_url: HttpUrl | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    relationship_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    verified: bool = False
    viewer_is_author: bool = False

    @model_validator(mode="after")
    def validate_typed_identity(self) -> PostAuthor:
        if self.author_type is PostAuthorType.MEMBER and not self.profile_slug:
            raise ValueError("A member post author requires profile_slug")
        if self.author_type is PostAuthorType.COMPANY and not self.company_slug:
            raise ValueError("A company post author requires company_slug")
        return self
