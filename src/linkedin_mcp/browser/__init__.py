"""Authorized Playwright browser lifecycle and page guards."""

from .bootstrap import BrowserRuntimeBootstrap
from .manager import BrowserManager, login_interactively

__all__ = ["BrowserManager", "BrowserRuntimeBootstrap", "login_interactively"]
