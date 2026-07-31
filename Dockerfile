# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm

ARG UV_VERSION=0.11.12

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
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN groupadd --system --gid 10001 linkedin-mcp \
    && useradd --system --uid 10001 --gid linkedin-mcp --home-dir /nonexistent linkedin-mcp \
    && mkdir -p /data/linkedin-mcp \
    && chown -R linkedin-mcp:linkedin-mcp /data/linkedin-mcp

USER linkedin-mcp

VOLUME ["/data/linkedin-mcp"]

ENTRYPOINT ["linkedin-mcp"]
CMD ["serve", "--transport", "stdio"]
