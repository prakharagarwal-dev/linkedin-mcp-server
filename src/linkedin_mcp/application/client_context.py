"""Internal MCP-client identity and browser-operation context."""

from __future__ import annotations

import uuid
import weakref
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from linkedin_mcp.application.pagination import PaginationLease

LOCAL_CLIENT_ID = "direct-local-client"


@dataclass(frozen=True, slots=True)
class ClientExecutionContext:
    """Server-owned identity and any resource reserved for one atomic call."""

    client_id: str
    pagination_lease: PaginationLease | None = None


_CURRENT_CONTEXT: ContextVar[ClientExecutionContext | None] = ContextVar(
    "linkedin_mcp_client_execution_context",
    default=None,
)


def current_execution_context() -> ClientExecutionContext:
    return _CURRENT_CONTEXT.get() or ClientExecutionContext(client_id=LOCAL_CLIENT_ID)


def current_client_id() -> str:
    return current_execution_context().client_id


@contextmanager
def bind_client_execution(
    client_id: str,
    *,
    pagination_lease: PaginationLease | None = None,
) -> Generator[None, None, None]:
    """Bind server-owned call state for the duration of one async execution path."""

    token = _CURRENT_CONTEXT.set(
        ClientExecutionContext(
            client_id=client_id,
            pagination_lease=pagination_lease,
        )
    )
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


class ClientSessionRegistry:
    """Assign an opaque process-local ID to each real MCP server session."""

    def __init__(self) -> None:
        self._ids: weakref.WeakKeyDictionary[object, str] = weakref.WeakKeyDictionary()

    def resolve(self, session: object) -> str:
        client_id = self._ids.get(session)
        if client_id is None:
            client_id = f"mcp-session-{uuid.uuid4()}"
            self._ids[session] = client_id
        return client_id

    @property
    def connected_count(self) -> int:
        return len(self._ids)
