"""Typed failures that can be safely projected through MCP."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    ACCESS_PAUSED = "access_paused"
    AUTHENTICATION_REQUIRED = "authentication_required"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_TARGET = "invalid_target"
    RESTRICTION_DETECTED = "restriction_detected"
    PARSER_DRIFT = "parser_drift"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    INTERNAL_ERROR = "internal_error"


class LinkedInMCPError(Exception):
    """Base error with a stable public code and operational semantics."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        pause_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.retryable = retryable
        self.pause_required = pause_required


class ConfigurationError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.CONFIGURATION_ERROR, message, pause_required=True)


class AccessPausedError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.ACCESS_PAUSED, message)


class AuthenticationRequiredError(LinkedInMCPError):
    def __init__(self, message: str = "LinkedIn authentication is required.") -> None:
        super().__init__(ErrorCode.AUTHENTICATION_REQUIRED, message, pause_required=True)


class IdempotencyConflictError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.IDEMPOTENCY_CONFLICT, message)


class InvalidCursorError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INVALID_CURSOR, message)


class InvalidTargetError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.INVALID_TARGET, message)


class RestrictionDetectedError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.RESTRICTION_DETECTED, message, pause_required=True)


class ParserDriftError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.PARSER_DRIFT, message, retryable=False)


class BrowserUnavailableError(LinkedInMCPError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.BROWSER_UNAVAILABLE, message, retryable=True)


class InternalServerError(LinkedInMCPError):
    def __init__(self, message: str = "The capability failed unexpectedly.") -> None:
        super().__init__(ErrorCode.INTERNAL_ERROR, message)
