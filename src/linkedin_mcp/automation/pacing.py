"""In-process navigation pacing for the single local LinkedIn worker."""

from __future__ import annotations

from math import ceil

from pyrate_limiter import Limiter, Rate


class NavigationPacer:
    """Wait for one process-local navigation permit at a time."""

    def __init__(self, *, account_id: str, interval_seconds: float) -> None:
        self._key = f"linkedin-navigation:{account_id}"
        self._limiter: Limiter | None = None
        if interval_seconds <= 0:
            return
        interval_ms = max(1, ceil(interval_seconds * 1_000))
        self._limiter = Limiter(Rate(1, interval_ms), buffer_ms=0)
        # A quick server restart must not create an immediate navigation burst.
        self._limiter.try_acquire(self._key, blocking=False)

    async def wait(self) -> None:
        limiter = self._limiter
        if limiter is None:
            return
        acquired = await limiter.try_acquire_async(self._key, blocking=True, timeout=-1)
        if not acquired:
            raise RuntimeError("The navigation pacer failed to issue a permit.")

    def close(self) -> None:
        limiter = self._limiter
        self._limiter = None
        if limiter is not None:
            limiter.close()
