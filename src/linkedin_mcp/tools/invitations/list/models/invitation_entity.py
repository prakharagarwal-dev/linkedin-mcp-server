"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import Identifier, StrictModel
from linkedin_mcp.tools.invitations.list.models.invitation_entity_type import InvitationEntityType


class InvitationEntity(StrictModel):
    entity_ref: Identifier
    entity_type: InvitationEntityType
    entity_url: HttpUrl | None = None
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
    slug: (
        Annotated[
            str,
            StringConstraints(
                min_length=1,
                max_length=200,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,199}$",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_known_entity_identity(self) -> InvitationEntity:
        if self.entity_type is not InvitationEntityType.OTHER and (
            self.entity_url is None or self.slug is None
        ):
            raise ValueError("Known invitation entities require a canonical URL and slug")
        return self
