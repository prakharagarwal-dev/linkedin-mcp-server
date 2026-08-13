"""Render privacy-safe Shields endpoint files from a live validation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from tests.live.models import LiveToolResult, LiveToolStatus, LiveValidationReport

_BADGE_STYLE: dict[LiveToolStatus, tuple[str, str]] = {
    LiveToolStatus.PASSED: ("passing", "brightgreen"),
    LiveToolStatus.FAILED: ("failed", "red"),
    LiveToolStatus.BLOCKED: ("blocked", "orange"),
    LiveToolStatus.SKIPPED: ("not run", "lightgrey"),
    LiveToolStatus.SIMULATOR_ONLY: ("simulator", "blue"),
}


def render_status(report: LiveValidationReport, output_directory: Path) -> None:
    badges = output_directory / "badges"
    badges.mkdir(parents=True, exist_ok=True)
    for result in report.tool_results:
        _write_json(badges / f"{result.tool}.json", _badge_payload(result))
    _write_json(
        output_directory / "summary.json",
        {
            "schema_version": 1,
            "run_id": report.run_id,
            "completed_at": report.completed_at.isoformat(),
            "overall_status": report.overall_status,
            "tools": {result.tool: result.status.value for result in report.tool_results},
        },
    )


def _badge_payload(result: LiveToolResult) -> dict[str, object]:
    message, color = _BADGE_STYLE[result.status]
    label = (
        result.tool.rsplit(".", maxsplit=1)[-1]
        if result.tool.endswith((".prepare", ".execute"))
        else "weekly live"
    )
    return {
        "schemaVersion": 1,
        "label": label,
        "message": message,
        "color": color,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Render live-validation status badges")
    value.add_argument("report", type=Path)
    value.add_argument("output_directory", type=Path)
    return value


def main() -> None:
    arguments = parser().parse_args()
    report_path = cast(Path, arguments.report)
    output_directory = cast(Path, arguments.output_directory)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    report = LiveValidationReport.model_validate(payload)
    render_status(report, output_directory)


if __name__ == "__main__":
    main()
