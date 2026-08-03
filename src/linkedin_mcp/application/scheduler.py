"""Bounded fair scheduling across independent local MCP clients."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Hashable
from typing import Final, cast

_CLOSED: Final = object()


class SchedulerClosedError(RuntimeError):
    """Raised when work is submitted to or requested from a closed scheduler."""


class FairClientScheduler[ClientKeyT: Hashable, ItemT]:
    """FIFO per client and round-robin across clients, with one global bound."""

    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Scheduler capacity must be positive.")
        self._queues: dict[ClientKeyT, deque[ItemT]] = {}
        self._ready: asyncio.Queue[ClientKeyT | object] = asyncio.Queue()
        self._slots = asyncio.BoundedSemaphore(capacity)
        self._lock = asyncio.Lock()
        self._last_client: ClientKeyT | None = None
        self._size = 0
        self._accepting = True

    @property
    def qsize(self) -> int:
        return self._size

    @property
    def client_count(self) -> int:
        return len(self._queues)

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def put(self, client: ClientKeyT, item: ItemT) -> None:
        await self._slots.acquire()
        admitted = False
        try:
            async with self._lock:
                if not self._accepting:
                    raise SchedulerClosedError("The scheduler is closed.")
                queue = self._queues.get(client)
                if queue is None:
                    queue = deque[ItemT]()
                    self._queues[client] = queue
                    self._ready.put_nowait(client)
                queue.append(item)
                self._size += 1
                admitted = True
        finally:
            if not admitted:
                self._slots.release()

    async def get(self) -> ItemT:
        while True:
            token = await self._ready.get()
            if token is _CLOSED:
                self._ready.put_nowait(_CLOSED)
                raise SchedulerClosedError("The scheduler is closed.")

            async with self._lock:
                clients = self._drain_ready(cast(ClientKeyT, token))
                if not clients:
                    if not self._accepting:
                        self._ready.put_nowait(_CLOSED)
                        raise SchedulerClosedError("The scheduler is closed.")
                    continue

                selected_index = 1 if len(clients) > 1 and clients[0] == self._last_client else 0
                selected_client = clients.pop(selected_index)
                queue = self._queues[selected_client]
                item = queue.popleft()
                self._size -= 1
                self._last_client = selected_client

                for waiting_client in (
                    *clients[selected_index:],
                    *clients[:selected_index],
                ):
                    self._ready.put_nowait(waiting_client)
                if queue:
                    self._ready.put_nowait(selected_client)
                else:
                    self._queues.pop(selected_client, None)

            self._slots.release()
            return item

    async def remove(self, client: ClientKeyT, item: ItemT) -> bool:
        async with self._lock:
            queue = self._queues.get(client)
            if queue is None:
                return False
            for index, queued in enumerate(queue):
                if queued is item:
                    del queue[index]
                    self._size -= 1
                    if not queue:
                        self._queues.pop(client, None)
                    self._slots.release()
                    return True
            return False

    async def close(self) -> tuple[ItemT, ...]:
        """Stop admission, drain queued items, and wake all waiters."""

        async with self._lock:
            if not self._accepting:
                return ()
            self._accepting = False
            drained = tuple(item for queue in self._queues.values() for item in queue)
            released_slots = self._size
            self._queues.clear()
            self._size = 0
            while True:
                try:
                    self._ready.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self._ready.put_nowait(_CLOSED)
        for _ in range(released_slots):
            self._slots.release()
        return drained

    def _drain_ready(self, first: ClientKeyT) -> list[ClientKeyT]:
        clients: list[ClientKeyT] = []
        observed: set[ClientKeyT] = set()
        tokens: list[ClientKeyT | object] = [first]
        while True:
            try:
                tokens.append(self._ready.get_nowait())
            except asyncio.QueueEmpty:
                break
        closed = False
        for token in tokens:
            if token is _CLOSED:
                closed = True
                continue
            client = cast(ClientKeyT, token)
            if client in self._queues and client not in observed:
                observed.add(client)
                clients.append(client)
        if closed:
            self._ready.put_nowait(_CLOSED)
        return clients
