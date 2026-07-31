from __future__ import annotations

import socket

import pytest

from tests.conftest import is_permitted_test_address


@pytest.mark.parametrize(
    "address",
    [
        ("127.0.0.1", 8000),
        ("::1", 8000, 0, 0),
        ("localhost", 8000),
        "/tmp/linkedin-mcp-test.sock",
    ],
)
def test_network_guard_allows_only_local_ipc(address: object) -> None:
    assert is_permitted_test_address(address)


@pytest.mark.parametrize(
    "address",
    [
        ("8.8.8.8", 443),
        ("example.com", 443),
        ("192.168.1.10", 8000),
        object(),
    ],
)
def test_network_guard_rejects_external_or_unknown_addresses(address: object) -> None:
    assert not is_permitted_test_address(address)


def test_default_suite_blocks_external_socket_connections() -> None:
    with socket.socket() as client, pytest.raises(AssertionError, match="External network"):
        client.connect(("example.com", 443))
