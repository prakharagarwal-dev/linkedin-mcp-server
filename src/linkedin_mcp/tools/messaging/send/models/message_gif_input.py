from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class MessageGifInput(StrictModel):
    search_query: Annotated[str, Field(min_length=1, max_length=200)]
    result_title: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description=(
                "Exact title exposed inside the current KLIPY result image alternative text."
            ),
        ),
    ]
