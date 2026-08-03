"""Authorized Playwright browser lifecycle and page guards."""

from .bootstrap import BrowserRuntimeBootstrap
from .manager import BrowserManager, login_interactively, logout_interactively
from .profile import BrowserProfileManager, BrowserProfileResetResult, BrowserProfileStatus

__all__ = [
    "BrowserManager",
    "BrowserProfileManager",
    "BrowserProfileResetResult",
    "BrowserProfileStatus",
    "BrowserRuntimeBootstrap",
    "login_interactively",
    "logout_interactively",
]
