from __future__ import annotations

import pytest

from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.models import CapabilityName
from linkedin_mcp.errors import AuthorizationDeniedError
from linkedin_mcp.policy import AuthorizationPolicy


def test_authorization_policy_allows_only_a_fully_enabled_descriptor() -> None:
    descriptor = create_default_registry().get(CapabilityName.JOBS_SEARCH)

    AuthorizationPolicy(Settings()).authorize(descriptor)

    with pytest.raises(AuthorizationDeniedError, match=r"linkedin\.jobs\.search"):
        AuthorizationPolicy(Settings(allowed_scopes=frozenset())).authorize(descriptor)
