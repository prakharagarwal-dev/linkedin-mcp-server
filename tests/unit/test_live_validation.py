from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from mcp import ClientSession
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from tests.live.manifest import (
    INVITATION_MUTATION_TOOLS,
    LIVE_ALLOWED_SCOPES,
    LIVE_EXECUTE_ALLOWLIST,
    LIVE_REQUIRED_TOOLS,
    all_public_tools,
)
from tests.live.models import LiveToolResult, LiveToolStatus, LiveValidationReport
from tests.live.runner import (
    LiveConfiguration,
    LiveRecorder,
    LiveScenario,
    Probe,
    _execute_arguments,  # pyright: ignore[reportPrivateUsage]
    _safe_result_error_code,  # pyright: ignore[reportPrivateUsage]
    _validate_prepare,  # pyright: ignore[reportPrivateUsage]
)
from tests.live.status import render_status


@dataclass(frozen=True, slots=True)
class _ToolStub:
    name: str


@dataclass(frozen=True, slots=True)
class _ToolListStub:
    tools: tuple[_ToolStub, ...]


class _SessionStub:
    async def list_tools(self) -> _ToolListStub:
        return _ToolListStub(tuple(_ToolStub(name) for name in all_public_tools()))


class _ScenarioRecorder(LiveRecorder):
    def __init__(self, config: LiveConfiguration) -> None:
        super().__init__(config)
        self.called: list[str] = []
        self.post_text = ""
        self.comment_text = ""
        self.message_text = ""

    async def probe(
        self,
        session: ClientSession,
        tool: str,
        arguments: Mapping[str, object],
    ) -> Probe:
        del session
        self.called.append(tool)
        content = self._content(tool, arguments)
        return Probe(
            status=LiveToolStatus.PASSED,
            duration_seconds=0.01,
            detail="offline scenario fixture",
            content=content,
        )

    def _content(self, tool: str, arguments: Mapping[str, object]) -> dict[str, object]:
        if tool == "linkedin.server.status":
            return {"accepting_calls": True}
        if tool == "linkedin.capabilities.list":
            domain_tools = all_public_tools() - {
                "linkedin.server.status",
                "linkedin.session.status",
                "linkedin.capabilities.list",
            }
            return {
                "capabilities": [
                    {
                        "name": name,
                        "enabled": name not in INVITATION_MUTATION_TOOLS,
                    }
                    for name in domain_tools
                ]
            }
        if tool == "linkedin.session.status":
            return {"authentication_state": "authenticated", "paused": False}
        if tool == "linkedin.people.get":
            slug = cast(str, arguments["profile_slug"])
            return {
                "person": {
                    "profile_slug": slug,
                    "name": "Account A" if slug.endswith("a") else "Account B",
                }
            }
        if tool in {"linkedin.people.search", "linkedin.connections.search"}:
            return _page(
                "people",
                [{"profile_slug": "test-account-b"}],
            )
        if tool == "linkedin.jobs.search":
            return _page("jobs", [{"job_id": "123456789"}])
        if tool == "linkedin.jobs.get":
            return {"job": {"job_id": "123456789", "description_text": "Fixture JD"}}
        if tool == "linkedin.companies.search":
            return _page("companies", [{"company_slug": "linkedin"}])
        if tool == "linkedin.companies.get":
            return {
                "company": {
                    "company_slug": "linkedin",
                    "coverage": {"pages_visited": 2},
                }
            }
        if tool == "linkedin.connections.list":
            return _page("connections", [{"profile_slug": "test-account-b"}])
        if tool == "linkedin.invitations.list":
            return _page("invitations", [])
        if tool == "linkedin.posts.create.prepare":
            post_content = cast(Mapping[str, object], arguments["content"])
            self.post_text = cast(str, post_content["text"])
            return _prepared("post_create", "a")
        if tool == "linkedin.posts.create.execute":
            return _executed("post_published:activity:7312345678901234567")
        if tool == "linkedin.posts.search":
            return _page(
                "posts",
                [
                    {
                        "post_ref": "activity:7312345678901234567",
                        "text": self.post_text,
                        "author": {"profile_slug": "test-account-a"},
                    }
                ],
            )
        if tool == "linkedin.posts.comment.prepare":
            self.comment_text = cast(str, arguments["text"])
            return _prepared("comment_create", "b")
        if tool == "linkedin.posts.comment.execute":
            return _executed("comment_published:comment:activity:7312345678901234567:1")
        if tool == "linkedin.posts.reaction.prepare":
            return _prepared("reaction_set", "c")
        if tool == "linkedin.posts.reaction.execute":
            return _executed("reaction_set:like")
        if tool == "linkedin.posts.comments.list":
            return _page(
                "threads",
                [
                    {
                        "comment": {
                            "comment_ref": "comment:activity:7312345678901234567:1",
                            "text": self.comment_text,
                        }
                    }
                ],
            )
        if tool == "linkedin.posts.get":
            return {
                "post": {
                    "post_ref": "activity:7312345678901234567",
                    "text": self.post_text,
                }
            }
        if tool == "linkedin.messaging.message.prepare":
            self.message_text = cast(str, arguments["message"])
            return _prepared("message_send", "d")
        if tool == "linkedin.messaging.message.execute":
            return _executed("message_sent")
        if tool == "linkedin.messaging.search":
            return _page(
                "conversations",
                [{"conversation_ref": "conversation:" + "1" * 24}],
            )
        if tool == "linkedin.messaging.conversation.get":
            return {
                "conversation": {
                    "is_group": False,
                    "messages": [{"text": self.message_text}],
                }
            }
        raise AssertionError(f"Unexpected scenario tool: {tool}")


def _page(field: str, items: list[dict[str, object]]) -> dict[str, object]:
    return {
        field: items,
        "pagination": {"has_more": False, "next_cursor": None},
    }


def _prepared(action_type: str, hash_character: str) -> dict[str, object]:
    payload_hash = hash_character * 64
    action_id = f"00000000-0000-4000-8000-00000000000{hash_character}"
    return {
        "status": "ready_for_confirmation",
        "draft": {
            "action_id": action_id,
            "action_type": action_type,
            "payload_hash": payload_hash,
        },
        "approval_preview": {
            "action_id": action_id,
            "action_type": action_type,
            "payload_hash": payload_hash,
        },
    }


def _executed(final_state: str) -> dict[str, object]:
    return {
        "result": {
            "outcome": "verified",
            "performed": True,
            "final_state": final_state,
        }
    }


def _configuration(tmp_path: Path) -> LiveConfiguration:
    profile_a = tmp_path / "profile-a"
    profile_b = tmp_path / "profile-b"
    profile_a.mkdir()
    profile_b.mkdir()
    return LiveConfiguration(
        account_a_slug="test-account-a",
        account_b_slug="test-account-b",
        account_a_profile_path=profile_a,
        account_b_profile_path=profile_b,
        work_root=tmp_path / "work",
        output_path=tmp_path / "report.json",
    )


def _complete_report() -> LiveValidationReport:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    results = tuple(
        LiveToolResult(
            tool=tool,
            status=(
                LiveToolStatus.SIMULATOR_ONLY
                if tool in INVITATION_MUTATION_TOOLS
                else LiveToolStatus.PASSED
            ),
            account="none" if tool in INVITATION_MUTATION_TOOLS else "account_a",
            calls=0 if tool in INVITATION_MUTATION_TOOLS else 1,
            duration_seconds=0.5,
            detail="sanitized test result",
        )
        for tool in sorted(all_public_tools())
    )
    return LiveValidationReport(
        run_id="live-20260812T000000Z-abcdef12",
        started_at=now,
        completed_at=now,
        overall_status="passed",
        tool_results=results,
    )


def test_live_manifest_covers_all_tools_with_only_invitation_mutations_excluded() -> None:
    assert len(all_public_tools()) == 31
    assert len(LIVE_REQUIRED_TOOLS) == 25
    assert len(INVITATION_MUTATION_TOOLS) == 6
    assert all_public_tools() == LIVE_REQUIRED_TOOLS | INVITATION_MUTATION_TOOLS
    assert LIVE_REQUIRED_TOOLS.isdisjoint(INVITATION_MUTATION_TOOLS)
    assert {
        "linkedin.posts.create.execute",
        "linkedin.posts.comment.execute",
        "linkedin.posts.reaction.execute",
        "linkedin.messaging.message.execute",
    } == LIVE_EXECUTE_ALLOWLIST
    assert all(not tool.startswith("linkedin.invitations.") for tool in LIVE_EXECUTE_ALLOWLIST)
    assert {
        "linkedin.invitations.send",
        "linkedin.invitations.accept",
        "linkedin.invitations.ignore",
    }.isdisjoint(LIVE_ALLOWED_SCOPES)


def test_live_workflow_uses_bounded_oidc_aws_orchestration() -> None:
    workflow = (Path(__file__).parents[2] / ".github/workflows/live-validation.yml").read_text()

    trigger_block = workflow.split("permissions:", 1)[0]
    assert "pull_request" not in trigger_block
    assert "push:" not in trigger_block
    assert "runs-on: ubuntu-latest" in workflow
    assert "environment: linkedin-live" in workflow
    assert "id-token: write" in workflow
    assert "aws-actions/configure-aws-credentials@" in workflow
    assert "aws ec2 start-instances" in workflow
    assert "aws ssm send-command" in workflow
    assert "aws ec2 stop-instances" in workflow
    assert "- name: Stop the EC2 worker\n        if: always()" in workflow
    assert "contents: write" in workflow
    assert "secrets." not in workflow


def test_live_aws_template_retains_encrypted_profiles_without_inbound_access() -> None:
    template = (Path(__file__).parents[2] / "infra/aws-live-validation/template.yaml").read_text()

    assert "Type: AWS::EC2::Volume" in template
    assert "DeletionPolicy: Retain" in template
    assert "UpdateReplacePolicy: Retain" in template
    assert "Encrypted: true" in template
    assert "VolumeType: gp3" in template
    assert "SecurityGroupIngress: []" in template
    assert "HttpTokens: required" in template
    assert "AmazonSSMManagedInstanceCore" in template
    assert (
        "repo:${GitHubOwner}/${GitHubRepository}:environment:${GitHubEnvironmentName}" in template
    )
    assert "AWS-RunShellScript" in template
    assert "linkedin-live-watchdog.timer" in template
    assert "AccessKey" not in template
    assert "SecretAccessKey" not in template


def test_live_ec2_wrapper_returns_only_bounded_sanitized_artifact() -> None:
    wrapper = (
        Path(__file__).parents[2] / "infra/aws-live-validation/run-live-validation.sh"
    ).read_text()

    assert "tests.live.runner" in wrapper
    assert "tests.live.status" in wrapper
    assert "archive_bytes > 16000" in wrapper
    assert "LINKEDIN_LIVE_ARCHIVE_BEGIN" in wrapper
    assert "LINKEDIN_LIVE_ARCHIVE_END" in wrapper
    assert "playwright install chromium" in wrapper


def test_live_configuration_requires_distinct_profiles(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    with pytest.raises(ValidationError, match="separate Chromium profile"):
        LiveConfiguration(
            account_a_slug="test-account-a",
            account_b_slug="test-account-b",
            account_a_profile_path=profile,
            account_b_profile_path=profile,
            work_root=tmp_path / "work",
            output_path=tmp_path / "report.json",
        )


def test_live_configuration_reads_only_paths_and_public_slugs_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_a = tmp_path / "profile-a"
    profile_b = tmp_path / "profile-b"
    profile_a.mkdir()
    profile_b.mkdir()
    (profile_a / "Local State").write_text("{}", encoding="utf-8")
    (profile_b / "Local State").write_text("{}", encoding="utf-8")
    profile_a.chmod(0o700)
    profile_b.chmod(0o700)
    monkeypatch.setenv("LINKEDIN_LIVE_ACCOUNT_A_SLUG", "test-account-a")
    monkeypatch.setenv("LINKEDIN_LIVE_ACCOUNT_B_SLUG", "test-account-b")
    monkeypatch.setenv("LINKEDIN_LIVE_ACCOUNT_A_PROFILE_PATH", str(profile_a))
    monkeypatch.setenv("LINKEDIN_LIVE_ACCOUNT_B_PROFILE_PATH", str(profile_b))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner"))

    config = LiveConfiguration.from_environment()

    assert config.account_a_profile_path == profile_a
    assert config.account_b_profile_path == profile_b
    assert config.output_path == tmp_path / "runner" / "linkedin-live-results" / "report.json"


@pytest.mark.asyncio
async def test_complete_live_scenario_orchestrates_every_repeatable_tool_without_invitation_writes(
    tmp_path: Path,
) -> None:
    config = _configuration(tmp_path)
    recorder = _ScenarioRecorder(config)
    session_a = cast(ClientSession, _SessionStub())
    session_b = cast(ClientSession, _SessionStub())
    run_id = "live-20260812T000000Z-abcdef12"

    await LiveScenario(
        config,
        recorder,
        run_id,
        session_a,
        session_b,
    ).run()
    report = recorder.finalize(
        run_id=run_id,
        started_at=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert report.overall_status == "passed"
    assert {result.tool for result in report.tool_results} == all_public_tools()
    assert all(
        result.status is LiveToolStatus.PASSED
        for result in report.tool_results
        if result.tool in LIVE_REQUIRED_TOOLS
    )
    assert set(recorder.called) >= LIVE_REQUIRED_TOOLS
    assert set(recorder.called).isdisjoint(INVITATION_MUTATION_TOOLS)
    assert {tool for tool in recorder.called if tool.endswith(".execute")} == LIVE_EXECUTE_ALLOWLIST


def test_prepare_preview_is_hash_locked_before_execute_arguments_are_built() -> None:
    content: dict[str, object] = {
        "status": "ready_for_confirmation",
        "draft": {
            "action_id": "00000000-0000-4000-8000-000000000000",
            "action_type": "message_send",
            "payload_hash": "a" * 64,
        },
        "approval_preview": {
            "action_id": "00000000-0000-4000-8000-000000000000",
            "action_type": "message_send",
            "payload_hash": "a" * 64,
        },
    }
    prepared = _validate_prepare(
        Probe(
            status=LiveToolStatus.PASSED,
            duration_seconds=0.1,
            detail="prepared",
            content=content,
        ),
        "message_send",
    )

    arguments = _execute_arguments(
        prepared,
        context_id="live-context",
        request_id="live-request",
        idempotency_key="live-idempotency",
    )

    assert arguments is not None
    assert arguments["payload_hash"] == "a" * 64
    assert arguments["approval_preview"] == content["approval_preview"]


def test_prepare_preview_rejects_a_changed_hash() -> None:
    prepared = _validate_prepare(
        Probe(
            status=LiveToolStatus.PASSED,
            duration_seconds=0.1,
            detail="prepared",
            content={
                "status": "ready_for_confirmation",
                "draft": {"action_type": "message_send", "payload_hash": "a" * 64},
                "approval_preview": {"payload_hash": "b" * 64},
            },
        ),
        "message_send",
    )

    assert prepared.status is LiveToolStatus.FAILED
    assert (
        _execute_arguments(
            prepared,
            context_id="live-context",
            request_id="live-request",
            idempotency_key="live-idempotency",
        )
        is None
    )


def test_tool_error_reporting_extracts_only_the_safe_error_code() -> None:
    result = CallToolResult(
        isError=True,
        content=[
            TextContent(
                type="text",
                text="Error executing tool: parser_drift: private visible content follows",
            )
        ],
    )

    assert _safe_result_error_code(result) == "parser_drift"


def test_recorder_marks_unreached_tools_and_keeps_invitation_mutations_simulator_only(
    tmp_path: Path,
) -> None:
    recorder = LiveRecorder(_configuration(tmp_path))
    started = datetime(2026, 8, 12, tzinfo=UTC)

    report = recorder.finalize(
        run_id="live-20260812T000000Z-abcdef12",
        started_at=started,
    )

    statuses = {result.tool: result.status for result in report.tool_results}
    assert report.overall_status == "failed"
    assert all(statuses[tool] is LiveToolStatus.SKIPPED for tool in LIVE_REQUIRED_TOOLS)
    assert all(
        statuses[tool] is LiveToolStatus.SIMULATOR_ONLY for tool in INVITATION_MUTATION_TOOLS
    )


def test_report_rejects_an_incomplete_tool_inventory() -> None:
    report = _complete_report()
    with pytest.raises(ValidationError, match="complete public tool inventory"):
        LiveValidationReport.model_validate(
            {
                **report.model_dump(mode="python"),
                "tool_results": report.tool_results[:-1],
            }
        )


def test_status_renderer_writes_only_safe_per_tool_states(tmp_path: Path) -> None:
    report = _complete_report()

    render_status(report, tmp_path)

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    search_badge = json.loads(
        (tmp_path / "badges" / "linkedin.jobs.search.json").read_text(encoding="utf-8")
    )
    invitation_badge = json.loads(
        (tmp_path / "badges" / "linkedin.invitations.send.execute.json").read_text(encoding="utf-8")
    )
    assert summary["overall_status"] == "passed"
    assert set(summary["tools"]) == all_public_tools()
    assert search_badge == {
        "schemaVersion": 1,
        "label": "weekly live",
        "message": "passing",
        "color": "brightgreen",
    }
    assert invitation_badge["message"] == "simulator"
    serialized = json.dumps(summary)
    assert "profile" not in serialized
    assert "cookie" not in serialized
    assert "message text" not in serialized
