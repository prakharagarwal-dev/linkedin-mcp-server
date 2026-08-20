"""Persistent Chromium lifecycle and visible LinkedIn authentication."""

from .bootstrap import BrowserBootstrap, BrowserSetupState
from .manager import BrowserManager
from .profile import BrowserProfileManager, BrowserProfileResetResult, BrowserProfileStatus

__all__ = [
    "BrowserBootstrap",
    "BrowserManager",
    "BrowserProfileManager",
    "BrowserProfileResetResult",
    "BrowserProfileStatus",
    "BrowserSetupState",
]
