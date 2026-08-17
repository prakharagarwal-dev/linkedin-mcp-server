"""Models for `linkedin_mcp.tools.invitations.send`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import Identifier, ProfileSlug, StrictModel


class InvitationSendInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
    note: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=(
                    "Optional personalized invitation note. LinkedIn currently limits "
                    "personalized invitations to 200 characters."
                ),
            ),
        ]
        | None
    ) = None
