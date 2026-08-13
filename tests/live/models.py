"""Sanitized machine-readable output for the scheduled live suite."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from linkedin_mcp.domain.models import StrictModel
from tests.live.manifest import all_public_tools


class LiveToolStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    SIMULATOR_ONLY = "simulator_only"


class LiveToolResult(StrictModel):
    tool: str = Field(pattern=r"^linkedin\.[a-z.]+$")
    status: LiveToolStatus
    account: Literal["account_a", "account_b", "both", "none"]
    calls: int = Field(ge=0, le=20)
    duration_seconds: float = Field(ge=0, le=7_200)
    detail: str = Field(min_length=1, max_length=300)


class LiveValidationReport(StrictModel):
    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^live-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
    started_at: datetime
    completed_at: datetime
    overall_status: Literal["passed", "failed"]
    account_count: Literal[2] = 2
    tool_results: tuple[LiveToolResult, ...]

    @model_validator(mode="after")
    def validate_complete_public_inventory(self) -> LiveValidationReport:
        names = tuple(result.tool for result in self.tool_results)
        if len(names) != len(set(names)):
            raise ValueError("Live validation results must contain each public tool once")
        if set(names) != set(all_public_tools()):
            raise ValueError(
                "Live validation results must cover the complete public tool inventory"
            )
        expected_status = (
            "passed"
            if all(
                result.status in {LiveToolStatus.PASSED, LiveToolStatus.SIMULATOR_ONLY}
                for result in self.tool_results
            )
            else "failed"
        )
        if self.overall_status != expected_status:
            raise ValueError("Live validation overall status conflicts with per-tool results")
        if self.completed_at < self.started_at:
            raise ValueError("Live validation completion precedes its start")
        return self

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def utc_now() -> datetime:
    return datetime.now(UTC)
