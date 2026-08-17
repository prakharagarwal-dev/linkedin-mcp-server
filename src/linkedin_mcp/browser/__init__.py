"""Generic Playwright runtime and persistent-profile infrastructure."""

from .bootstrap import BrowserRuntimeBootstrap, BrowserSetupState
from .profile import BrowserProfileManager, BrowserProfileResetResult, BrowserProfileStatus
from .runtime import BrowserRuntime

__all__ = [
    "BrowserProfileManager",
    "BrowserProfileResetResult",
    "BrowserProfileStatus",
    "BrowserRuntime",
    "BrowserRuntimeBootstrap",
    "BrowserSetupState",
]
