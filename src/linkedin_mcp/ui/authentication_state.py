"""Process-local authentication state observed by the LinkedIn UI facade."""

from enum import StrEnum


class AuthenticationState(StrEnum):
    LOGIN_REQUIRED = "login_required"
    AUTHENTICATED = "authenticated"
    ATTENTION_REQUIRED = "attention_required"
