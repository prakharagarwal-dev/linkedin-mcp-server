from __future__ import annotations

import gc

from linkedin_mcp.transport.context import (
    LOCAL_CLIENT_ID,
    ClientSessionRegistry,
    bind_client_execution,
    current_client_id,
)


class _Session:
    pass


def test_client_execution_context_is_nested_and_resets_to_local_default() -> None:
    assert current_client_id() == LOCAL_CLIENT_ID

    with bind_client_execution("client-a"):
        assert current_client_id() == "client-a"
        with bind_client_execution("client-b"):
            assert current_client_id() == "client-b"
        assert current_client_id() == "client-a"

    assert current_client_id() == LOCAL_CLIENT_ID


def test_session_registry_assigns_stable_opaque_weak_identities() -> None:
    registry = ClientSessionRegistry()
    first = _Session()
    second = _Session()

    first_id = registry.resolve(first)
    assert registry.resolve(first) == first_id
    assert registry.resolve(second) != first_id
    assert first_id.startswith("mcp-session-")
    assert registry.connected_count == 2

    del first
    gc.collect()
    assert registry.connected_count == 1
