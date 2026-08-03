"""Run the production stdio bridge against a test-owned loopback runtime."""

from __future__ import annotations

import asyncio
import sys

from linkedin_mcp.application.proxy import run_stdio_proxy

if __name__ == "__main__":
    asyncio.run(run_stdio_proxy(sys.argv[1]))
