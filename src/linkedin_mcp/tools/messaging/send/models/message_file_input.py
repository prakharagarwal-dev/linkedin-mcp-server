from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    AssetReference,
    StrictModel,
)


class MessageFileInput(StrictModel):
    asset_ref: AssetReference
