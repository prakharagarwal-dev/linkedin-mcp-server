# syntax=docker/dockerfile:1.7

FROM mcr.microsoft.com/playwright/python:v1.61.0-noble@sha256:a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69

ARG UV_VERSION=0.11.12
ARG VERSION=0.14.2

LABEL org.opencontainers.image.title="LinkedIn MCP Server" \
    org.opencontainers.image.description="Typed, policy-enforced local MCP capabilities over LinkedIn's visible web UI" \
    org.opencontainers.image.source="https://github.com/prakharagarwal-dev/linkedin-mcp-server" \
    org.opencontainers.image.url="https://github.com/prakharagarwal-dev/linkedin-mcp-server" \
    org.opencontainers.image.documentation="https://github.com/prakharagarwal-dev/linkedin-mcp-server#readme" \
    org.opencontainers.image.licenses="Apache-2.0" \
    org.opencontainers.image.version="${VERSION}" \
    io.modelcontextprotocol.server.name="io.github.prakharagarwal-dev/linkedin-mcp-server"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    LINKEDIN_MCP_BROWSER_PROFILE_PATH=/data/linkedin-mcp/profile \
    LINKEDIN_MCP_ASSET_ROOT_PATH=/data/linkedin-mcp/assets \
    LINKEDIN_MCP_AUTO_LOGIN_ON_START=false \
    LINKEDIN_MCP_RUNTIME_LOCK_PATH=/data/linkedin-mcp/runtime.lock \
    PATH=/app/.venv/bin:$PATH

RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev \
    && chmod -R a+rX /ms-playwright

RUN groupadd --system --gid 10001 linkedin-mcp \
    && useradd --system --uid 10001 --gid linkedin-mcp --home-dir /nonexistent linkedin-mcp \
    && mkdir -p /data/linkedin-mcp \
    && chown -R linkedin-mcp:linkedin-mcp /data/linkedin-mcp

USER linkedin-mcp

VOLUME ["/data/linkedin-mcp"]

ENTRYPOINT ["linkedin-mcp"]
CMD ["serve", "--transport", "stdio"]
