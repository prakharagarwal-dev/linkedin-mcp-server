"""POSIX singleton lock for the one local LinkedIn account runtime."""

from __future__ import annotations

import fcntl
import os
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from linkedin_mcp.errors import ConfigurationError


class AccountProcessLock:
    """Prevent two local MCP processes from controlling one browser session."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: TextIO | None = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self.acquired:
            return
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with suppress(OSError):
            self._path.parent.chmod(0o700)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            os.fchmod(handle.fileno(), 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            handle.close()
            raise ConfigurationError(
                "Another local LinkedIn MCP server already owns this account runtime."
            ) from error
        except Exception:
            handle.close()
            raise
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
