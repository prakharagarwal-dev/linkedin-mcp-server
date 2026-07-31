from __future__ import annotations

from pathlib import Path

import pytest

from linkedin_mcp.application import AccountProcessLock
from linkedin_mcp.config import Settings
from linkedin_mcp.container import create_production_container
from linkedin_mcp.domain.models import CapabilityName
from linkedin_mcp.errors import ConfigurationError


@pytest.mark.asyncio
async def test_production_container_composes_and_closes_without_connecting() -> None:
    container = create_production_container(Settings())

    assert container.registry.get(CapabilityName.JOBS_SEARCH).version == "2.1.0"
    assert container.registry.get(CapabilityName.PEOPLE_SEARCH).version == "2.1.0"
    assert container.registry.get(CapabilityName.PEOPLE_GET).version == "1.1.1"
    assert container.registry.get(CapabilityName.COMPANIES_SEARCH).version == "2.0.0"
    assert container.registry.get(CapabilityName.COMPANIES_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.POSTS_SEARCH).version == "2.0.0"
    assert container.registry.get(CapabilityName.POSTS_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_COMMENTS_LIST).version == "1.1.1"
    assert container.registry.get(CapabilityName.INVITATIONS_LIST).version == "3.0.0"
    assert container.registry.get(CapabilityName.CONNECTIONS_LIST).version == "2.0.0"
    assert container.registry.get(CapabilityName.CONNECTIONS_SEARCH).version == "2.0.0"
    assert container.registry.get(CapabilityName.POSTS_CREATE_PREPARE).version == "2.0.0"
    assert container.registry.get(CapabilityName.POSTS_CREATE_EXECUTE).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_COMMENT_PREPARE).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_COMMENT_EXECUTE).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_REACTION_PREPARE).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_REACTION_EXECUTE).version == "2.0.0"
    assert container.registry.get(CapabilityName.INVITATION_SEND_PREPARE).version == "1.1.0"
    assert container.registry.get(CapabilityName.INVITATION_SEND_EXECUTE).version == "2.0.0"
    assert container.registry.get(CapabilityName.INVITATION_ACCEPT_PREPARE).version == "1.0.0"
    assert container.registry.get(CapabilityName.INVITATION_ACCEPT_EXECUTE).version == "1.0.0"
    assert container.registry.get(CapabilityName.INVITATION_IGNORE_PREPARE).version == "1.0.0"
    assert container.registry.get(CapabilityName.INVITATION_IGNORE_EXECUTE).version == "1.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_CONVERSATION_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_SEARCH).version == "2.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_MESSAGE_PREPARE).version == "2.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_MESSAGE_EXECUTE).version == "2.0.0"
    assert container.browser.started is False

    await container.close()


def test_account_process_lock_rejects_a_second_local_server(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    first = AccountProcessLock(path)
    second = AccountProcessLock(path)

    first.acquire()
    with pytest.raises(ConfigurationError, match="already owns"):
        second.acquire()
    first.release()

    second.acquire()
    assert second.acquired is True
    second.release()
