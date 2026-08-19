"""Persistent Chromium lifecycle and visible LinkedIn authentication."""

from .bootstrap import BrowserBootstrap, BrowserSetupState
from .manager import AuthenticationState, BrowserManager
from .profile import BrowserProfileManager, BrowserProfileResetResult, BrowserProfileStatus

__all__ = [
    "AuthenticationState",
    "BrowserBootstrap",
    "BrowserManager",
    "BrowserProfileManager",
    "BrowserProfileResetResult",
    "BrowserProfileStatus",
    "BrowserSetupState",
]
