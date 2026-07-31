"""Fail-closed capability authorization independent of MCP annotations."""

from linkedin_mcp.capabilities import CapabilityDescriptor
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import AuthorizationDeniedError


class AuthorizationPolicy:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize(self, descriptor: CapabilityDescriptor) -> None:
        status = descriptor.status(self._settings)
        if not status.enabled:
            reason = status.disabled_reason or "capability is disabled"
            raise AuthorizationDeniedError(f"{descriptor.name.value}: {reason}")
