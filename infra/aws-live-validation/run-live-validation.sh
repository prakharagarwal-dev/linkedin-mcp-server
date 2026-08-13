#!/usr/bin/env bash
set -euo pipefail
umask 077

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly REPOSITORY_ROOT
readonly PERSISTENT_ROOT=/var/lib/linkedin-mcp-live
readonly LOG_ROOT="$PERSISTENT_ROOT/logs"
RUN_ROOT="$(mktemp -d "$PERSISTENT_ROOT/work/run.XXXXXXXX")"
readonly RUN_ROOT
readonly RESULT_ROOT="$RUN_ROOT/artifact"
readonly RESULT_PATH="$RESULT_ROOT/report.json"
readonly STATUS_PATH="$RESULT_ROOT/linkedin-live-status"
readonly ARCHIVE_PATH="$RUN_ROOT/linkedin-live-results.tar.gz"
LOG_PATH="$LOG_ROOT/$(date -u +%Y%m%dT%H%M%SZ).log"
readonly LOG_PATH

trap 'rm -rf "$RUN_ROOT"' EXIT

mkdir -p "$LOG_ROOT" "$RESULT_ROOT"
exec 3>&1
exec >>"$LOG_PATH" 2>&1

export HOME=/home/linkedin-live
export UV_CACHE_DIR="$PERSISTENT_ROOT/cache/uv"
export PLAYWRIGHT_BROWSERS_PATH="$PERSISTENT_ROOT/cache/playwright"
export LINKEDIN_LIVE_RESULT_PATH="$RESULT_PATH"
export LINKEDIN_LIVE_WORK_ROOT="$RUN_ROOT/runtime"
export LINKEDIN_LIVE_CALL_INTERVAL_SECONDS=5
export LINKEDIN_LIVE_TOOL_TIMEOUT_SECONDS=420
export LINKEDIN_LIVE_MAX_CURSOR_PAGES=2
export LINKEDIN_LIVE_POST_SEARCH_ATTEMPTS=3

cd "$REPOSITORY_ROOT"
uv sync --frozen --all-groups
uv run playwright install chromium

set +e
uv run python -m tests.live.runner --output "$RESULT_PATH"
live_status=$?
set -e

test -f "$RESULT_PATH"
uv run python -m tests.live.status "$RESULT_PATH" "$STATUS_PATH"
test -f "$STATUS_PATH/summary.json"
test -d "$STATUS_PATH/badges"

tar -czf "$ARCHIVE_PATH" -C "$RESULT_ROOT" report.json linkedin-live-status
archive_bytes="$(wc -c <"$ARCHIVE_PATH" | tr -d ' ')"
if ((archive_bytes > 16000)); then
  echo "Sanitized live-result archive exceeded the bounded SSM output size." >&2
  exit 2
fi

printf 'LINKEDIN_LIVE_ARCHIVE_BEGIN\n' >&3
base64 --wrap=0 "$ARCHIVE_PATH" >&3
printf '\nLINKEDIN_LIVE_ARCHIVE_END\n' >&3
exit "$live_status"
