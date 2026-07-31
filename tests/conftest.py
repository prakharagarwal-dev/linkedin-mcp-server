from __future__ import annotations

import ipaddress
import socket
from collections.abc import Generator
from typing import Any, cast

import pytest


def is_permitted_test_address(address: object) -> bool:
    """Allow local IPC and loopback sockets while rejecting external test traffic."""

    if isinstance(address, (str, bytes)):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    parts = cast(tuple[object, ...], address)
    host = parts[0]
    if isinstance(host, bytes):
        host = host.decode(errors="ignore")
    if not isinstance(host, str):
        return False
    normalized = host.strip("[]").casefold()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None]:
    """Keep the complete test suite offline."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(instance: socket.socket, address: Any) -> None:
        if not is_permitted_test_address(address):
            raise AssertionError(f"External network access is forbidden in tests: {address!r}")
        original_connect(instance, address)

    def guarded_connect_ex(instance: socket.socket, address: Any) -> int:
        if not is_permitted_test_address(address):
            raise AssertionError(f"External network access is forbidden in tests: {address!r}")
        return original_connect_ex(instance, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    yield
