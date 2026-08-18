from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StopReason,
    StrictModel,
)


class ConversationCoverage(StrictModel):
    messages_observed: Annotated[int, Field(ge=0)]
    messages_returned: Annotated[int, Field(ge=0)]
    attachments_returned: Annotated[int, Field(ge=0)] = 0
    replies_returned: Annotated[int, Field(ge=0)] = 0
    reactions_returned: Annotated[int, Field(ge=0)] = 0
    max_messages: Annotated[int, Field(ge=1)]
    rounds_visited: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    history_complete: bool
    truncated: bool
    captured_at: datetime
