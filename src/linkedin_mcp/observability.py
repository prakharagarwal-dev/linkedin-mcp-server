"""Safe structured logging configuration for stdio and HTTP transports."""

from __future__ import annotations

import logging
import sys

import structlog


def _stderr_logger_factory(*args: object) -> structlog.PrintLogger:
    del args
    return structlog.PrintLogger(sys.stderr)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )
    structlog.configure(
        processors=(
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ),
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        logger_factory=_stderr_logger_factory,
        cache_logger_on_first_use=False,
    )
