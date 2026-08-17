from __future__ import annotations

import pytest

import linkedin_mcp.logging as logging_config


def test_stderr_logger_factory_uses_current_standard_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = logging_config._stderr_logger_factory(  # pyright: ignore[reportPrivateUsage]
        "ignored-structlog-argument"
    )

    logger.info("structured-event")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "structured-event\n"
