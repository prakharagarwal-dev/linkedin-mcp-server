"""State reported by generic browser runtime setup."""

from enum import StrEnum


class BrowserSetupState(StrEnum):
    DISABLED = "disabled"
    NOT_STARTED = "not_started"
    INSTALLING = "installing"
    READY = "ready"
    FAILED = "failed"
