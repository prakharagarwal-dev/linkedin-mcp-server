"""Run the bounded two-account live suite through the official MCP stdio transport.

This module is intentionally not a pytest test. The default suite remains fully
offline; GitHub Actions invokes this runner only on the dedicated live runner.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import stat
import sys
import time
from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult
from pydantic import Field, TypeAdapter, model_validator

from linkedin_mcp.domain.models import StrictModel
from linkedin_mcp.errors import ErrorCode
from tests.live.manifest import (
    INVITATION_MUTATION_TOOLS,
    LIVE_ALLOWED_SCOPES,
    LIVE_EXECUTE_ALLOWLIST,
    LIVE_REQUIRED_TOOLS,
    LIVE_STATUS_ORDER,
    all_public_tools,
)
from tests.live.models import (
    LiveToolResult,
    LiveToolStatus,
    LiveValidationReport,
    utc_now,
)
from tests.verification_manifest import MOCK_VERIFICATION

ROOT = Path(__file__).parents[2]
_DICT_ADAPTER = TypeAdapter(dict[str, object])
_LIST_ADAPTER = TypeAdapter(list[object])
_SAFE_ERROR_CODE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+):")
_POST_STATE = re.compile(r"^post_published:(?P<post_ref>(?:activity|share|ugc-post):[0-9]{5,30})$")
_BLOCKING_ERROR_CODES = frozenset(
    {
        "authentication_required",
        "authorization_denied",
        "browser_unavailable",
        "configuration_error",
        "restriction_detected",
    }
)

AccountName = Literal["account_a", "account_b", "both", "none"]


class LiveConfiguration(StrictModel):
    account_a_slug: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{1,198}[A-Za-z0-9-])?$")
    account_b_slug: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{1,198}[A-Za-z0-9-])?$")
    account_a_profile_path: Path
    account_b_profile_path: Path
    work_root: Path
    output_path: Path
    call_interval_seconds: float = Field(default=5.0, ge=2.0, le=120.0)
    tool_timeout_seconds: float = Field(default=420.0, ge=30.0, le=900.0)
    max_cursor_pages: int = Field(default=2, ge=1, le=3)
    post_search_attempts: int = Field(default=3, ge=1, le=3)

    @model_validator(mode="after")
    def validate_two_distinct_accounts(self) -> LiveConfiguration:
        if self.account_a_slug.casefold() == self.account_b_slug.casefold():
            raise ValueError("Live validation requires two distinct LinkedIn profiles")
        if self.account_a_profile_path.resolve() == self.account_b_profile_path.resolve():
            raise ValueError("Live validation requires a separate Chromium profile per account")
        return self

    @classmethod
    def from_environment(cls, output_override: Path | None = None) -> LiveConfiguration:
        runner_temp = Path(os.environ.get("RUNNER_TEMP", ".live-validation"))
        output_path = output_override or Path(
            os.environ.get(
                "LINKEDIN_LIVE_RESULT_PATH",
                str(runner_temp / "linkedin-live-results" / "report.json"),
            )
        )
        config = cls(
            account_a_slug=_required_environment("LINKEDIN_LIVE_ACCOUNT_A_SLUG"),
            account_b_slug=_required_environment("LINKEDIN_LIVE_ACCOUNT_B_SLUG"),
            account_a_profile_path=Path(
                _required_environment("LINKEDIN_LIVE_ACCOUNT_A_PROFILE_PATH")
            ),
            account_b_profile_path=Path(
                _required_environment("LINKEDIN_LIVE_ACCOUNT_B_PROFILE_PATH")
            ),
            work_root=Path(
                os.environ.get(
                    "LINKEDIN_LIVE_WORK_ROOT",
                    str(runner_temp / "linkedin-mcp-live"),
                )
            ),
            output_path=output_path,
            call_interval_seconds=float(os.environ.get("LINKEDIN_LIVE_CALL_INTERVAL_SECONDS", "5")),
            tool_timeout_seconds=float(os.environ.get("LINKEDIN_LIVE_TOOL_TIMEOUT_SECONDS", "420")),
            max_cursor_pages=int(os.environ.get("LINKEDIN_LIVE_MAX_CURSOR_PAGES", "2")),
            post_search_attempts=int(os.environ.get("LINKEDIN_LIVE_POST_SEARCH_ATTEMPTS", "3")),
        )
        for profile_path in (
            config.account_a_profile_path,
            config.account_b_profile_path,
        ):
            _validate_profile_directory(profile_path)
        return config


@dataclass(frozen=True, slots=True)
class AccountRuntime:
    name: Literal["account_a", "account_b"]
    slug: str
    profile_path: Path
    work_path: Path
    http_port: int


@dataclass(frozen=True, slots=True)
class Probe:
    status: LiveToolStatus
    duration_seconds: float
    detail: str
    calls: int = 1
    content: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class CollectionProbe:
    probe: Probe
    items: tuple[dict[str, object], ...]


class LiveRecorder:
    """Own one sanitized result per public tool and pace calls across both accounts."""

    def __init__(self, config: LiveConfiguration) -> None:
        self._config = config
        self._results: dict[str, LiveToolResult] = {}
        self._last_call_started: float | None = None

    async def probe(
        self,
        session: ClientSession,
        tool: str,
        arguments: Mapping[str, object],
    ) -> Probe:
        if tool.endswith(".execute") and tool not in LIVE_EXECUTE_ALLOWLIST:
            return Probe(
                status=LiveToolStatus.BLOCKED,
                duration_seconds=0,
                detail="execute tool is outside the live client allowlist",
                calls=0,
            )
        await self._pace()
        started = time.monotonic()
        try:
            result = await session.call_tool(
                tool,
                dict(arguments),
                read_timeout_seconds=timedelta(seconds=self._config.tool_timeout_seconds),
            )
        except TimeoutError:
            return Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=time.monotonic() - started,
                detail="MCP call exceeded its bounded client timeout",
            )
        except Exception as error:
            return Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=time.monotonic() - started,
                detail=f"MCP client failure ({type(error).__name__})",
            )
        duration = time.monotonic() - started
        if result.isError:
            error_code = _safe_result_error_code(result)
            status = (
                LiveToolStatus.BLOCKED
                if error_code in _BLOCKING_ERROR_CODES
                else LiveToolStatus.FAILED
            )
            return Probe(
                status=status,
                duration_seconds=duration,
                detail=f"MCP tool error ({error_code})",
            )
        if result.structuredContent is None:
            return Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=duration,
                detail="MCP result omitted structured content",
            )
        try:
            content = _DICT_ADAPTER.validate_python(result.structuredContent)
        except Exception:
            return Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=duration,
                detail="MCP result violated the structured-content contract",
            )
        return Probe(
            status=LiveToolStatus.PASSED,
            duration_seconds=duration,
            detail="MCP call completed",
            content=content,
        )

    def record(
        self,
        tool: str,
        account: AccountName,
        probes: Probe | Sequence[Probe],
        *,
        success_detail: str,
    ) -> None:
        if tool in self._results:
            raise RuntimeError(f"Live tool result already recorded: {tool}")
        values = (probes,) if isinstance(probes, Probe) else tuple(probes)
        if not values:
            raise ValueError("At least one probe is required")
        status = max(values, key=lambda value: LIVE_STATUS_ORDER[value.status.value]).status
        detail = (
            success_detail
            if status is LiveToolStatus.PASSED
            else next(value.detail for value in values if value.status is status)
        )
        result = LiveToolResult(
            tool=tool,
            status=status,
            account=account,
            calls=sum(value.calls for value in values),
            duration_seconds=round(sum(value.duration_seconds for value in values), 3),
            detail=detail,
        )
        self._results[tool] = result
        print(f"{tool}: {status.value} ({detail})", flush=True)

    def skip(self, tool: str, account: AccountName, detail: str) -> None:
        if tool in self._results:
            return
        self._results[tool] = LiveToolResult(
            tool=tool,
            status=LiveToolStatus.SKIPPED,
            account=account,
            calls=0,
            duration_seconds=0,
            detail=detail,
        )
        print(f"{tool}: skipped ({detail})", flush=True)

    def finalize(
        self,
        *,
        run_id: str,
        started_at: Any,
    ) -> LiveValidationReport:
        for tool in INVITATION_MUTATION_TOOLS:
            self._results.setdefault(
                tool,
                LiveToolResult(
                    tool=tool,
                    status=LiveToolStatus.SIMULATOR_ONLY,
                    account="none",
                    calls=0,
                    duration_seconds=0,
                    detail="excluded from the stable two-account live loop",
                ),
            )
        for tool in LIVE_REQUIRED_TOOLS:
            self.skip(tool, "none", "live runner stopped before this tool was reached")
        ordered = tuple(self._results[tool] for tool in MOCK_VERIFICATION)
        overall = (
            "passed"
            if all(
                result.status in {LiveToolStatus.PASSED, LiveToolStatus.SIMULATOR_ONLY}
                for result in ordered
            )
            else "failed"
        )
        return LiveValidationReport(
            run_id=run_id,
            started_at=started_at,
            completed_at=utc_now(),
            overall_status=overall,
            tool_results=ordered,
        )

    async def _pace(self) -> None:
        now = time.monotonic()
        if self._last_call_started is not None:
            delay = self._config.call_interval_seconds - (now - self._last_call_started)
            if delay > 0:
                await asyncio.sleep(delay)
        self._last_call_started = time.monotonic()


class LiveScenario:
    def __init__(
        self,
        config: LiveConfiguration,
        recorder: LiveRecorder,
        run_id: str,
        account_a: ClientSession,
        account_b: ClientSession,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._run_id = run_id
        self._account_a = account_a
        self._account_b = account_b
        self._request_counter = 0

    async def run(self) -> None:
        await self._validate_discovery()
        await self._operational_tools()
        names = await self._people_tools()
        await self._session_status()
        await self._jobs_tools()
        await self._company_tools()
        await self._network_tools(names)
        post_ref = await self._post_creation()
        await self._post_read_and_engagement(post_ref)
        await self._messaging_tools(names)

    async def _validate_discovery(self) -> None:
        expected = all_public_tools()
        for session in (self._account_a, self._account_b):
            discovered = await session.list_tools()
            names = {tool.name for tool in discovered.tools}
            if names != set(expected):
                raise RuntimeError("MCP discovery does not match the public verification inventory")

    async def _operational_tools(self) -> None:
        status = await self._recorder.probe(
            self._account_a,
            "linkedin.server.status",
            {},
        )
        status = _validate_probe(
            status,
            lambda content: _require(content.get("accepting_calls") is True),
        )
        self._recorder.record(
            "linkedin.server.status",
            "account_a",
            status,
            success_detail="shared runtime is accepting calls",
        )

        capabilities = await self._recorder.probe(
            self._account_a,
            "linkedin.capabilities.list",
            {},
        )

        def validate_capabilities(content: dict[str, object]) -> None:
            rows = _mapping_items(content, "capabilities")
            enabled = {_string(row, "name") for row in rows if row.get("enabled") is True}
            domain_tools = all_public_tools() - {
                "linkedin.server.status",
                "linkedin.session.status",
                "linkedin.capabilities.list",
            }
            _require({_string(row, "name") for row in rows} == set(domain_tools))
            _require(
                LIVE_REQUIRED_TOOLS
                - {
                    "linkedin.server.status",
                    "linkedin.session.status",
                    "linkedin.capabilities.list",
                }
                <= enabled
            )
            _require(INVITATION_MUTATION_TOOLS.isdisjoint(enabled))

        capabilities = _validate_probe(capabilities, validate_capabilities)
        self._recorder.record(
            "linkedin.capabilities.list",
            "account_a",
            capabilities,
            success_detail="repeatable capabilities enabled; invitation mutations disabled",
        )

    async def _people_tools(self) -> dict[str, str]:
        probes: list[Probe] = []
        names: dict[str, str] = {}
        for account_name, session, target_slug in (
            ("account_a", self._account_a, self._config.account_b_slug),
            ("account_b", self._account_b, self._config.account_a_slug),
        ):
            probe = await self._recorder.probe(
                session,
                "linkedin.people.get",
                {
                    "context_id": self._context("people-get"),
                    "request_id": self._request("people-get"),
                    "profile_slug": target_slug,
                    "sections": ["overview"],
                },
            )

            def validate(
                content: dict[str, object],
                expected_slug: str = target_slug,
                result_account: str = account_name,
            ) -> None:
                person = _mapping(content, "person")
                _require(_string(person, "profile_slug").casefold() == expected_slug.casefold())
                names[result_account] = _string(person, "name")

            probes.append(_validate_probe(probe, validate))
        self._recorder.record(
            "linkedin.people.get",
            "both",
            probes,
            success_detail="each account read the other test profile overview",
        )

        target_name = names.get("account_a")
        if target_name is None:
            self._recorder.skip(
                "linkedin.people.search",
                "account_a",
                "counterpart profile identity was unavailable",
            )
            return names
        collection = await self._collection(
            self._account_a,
            "linkedin.people.search",
            "account_a",
            base_arguments={"query": target_name, "filters": {"connection_degrees": ["first"]}},
            item_field="people",
            identity=lambda item: _string(item, "profile_slug"),
            require_items=True,
        )
        if collection.probe.status is LiveToolStatus.PASSED:
            collection = CollectionProbe(
                probe=_validate_probe(
                    collection.probe,
                    lambda _content: _require(
                        any(
                            _string(item, "profile_slug").casefold()
                            == self._config.account_b_slug.casefold()
                            for item in collection.items
                        )
                    ),
                ),
                items=collection.items,
            )
        self._recorder.record(
            "linkedin.people.search",
            "account_a",
            collection.probe,
            success_detail="exact counterpart found through first-degree People search",
        )
        return names

    async def _session_status(self) -> None:
        probes: list[Probe] = []
        for session in (self._account_a, self._account_b):
            probe = await self._recorder.probe(session, "linkedin.session.status", {})
            probes.append(
                _validate_probe(
                    probe,
                    lambda content: _require(
                        content.get("authentication_state") == "authenticated"
                        and content.get("paused") is False
                    ),
                )
            )
        self._recorder.record(
            "linkedin.session.status",
            "both",
            probes,
            success_detail="both persistent sessions are authenticated and unpaused",
        )

    async def _jobs_tools(self) -> None:
        jobs = await self._collection(
            self._account_a,
            "linkedin.jobs.search",
            "account_a",
            base_arguments={"query": "software engineer"},
            item_field="jobs",
            identity=lambda item: _string(item, "job_id"),
            require_items=True,
        )
        self._recorder.record(
            "linkedin.jobs.search",
            "account_a",
            jobs.probe,
            success_detail=_collection_detail(jobs.probe, jobs.items),
        )
        if not jobs.items:
            self._recorder.skip(
                "linkedin.jobs.get",
                "account_a",
                "job search produced no exact job target",
            )
            return
        job_id = _string(jobs.items[0], "job_id")
        detail = await self._recorder.probe(
            self._account_a,
            "linkedin.jobs.get",
            {
                "context_id": self._context("job-get"),
                "request_id": self._request("job-get"),
                "job_id": job_id,
            },
        )
        detail = _validate_probe(
            detail,
            lambda content: _require(
                _string(_mapping(content, "job"), "job_id") == job_id
                and bool(_mapping(content, "job").get("description_text"))
            ),
        )
        self._recorder.record(
            "linkedin.jobs.get",
            "account_a",
            detail,
            success_detail="search result returned an expanded visible job description",
        )

    async def _company_tools(self) -> None:
        companies = await self._collection(
            self._account_a,
            "linkedin.companies.search",
            "account_a",
            base_arguments={"query": "LinkedIn"},
            item_field="companies",
            identity=lambda item: _string(item, "company_slug"),
            require_items=True,
        )
        self._recorder.record(
            "linkedin.companies.search",
            "account_a",
            companies.probe,
            success_detail=_collection_detail(companies.probe, companies.items),
        )
        if not companies.items:
            self._recorder.skip(
                "linkedin.companies.get",
                "account_a",
                "company search produced no exact company target",
            )
            return
        slug = _string(companies.items[0], "company_slug")
        detail = await self._recorder.probe(
            self._account_a,
            "linkedin.companies.get",
            {
                "context_id": self._context("company-get"),
                "request_id": self._request("company-get"),
                "company_slug": slug,
            },
        )
        detail = _validate_probe(
            detail,
            lambda content: _require(
                _string(_mapping(content, "company"), "company_slug") == slug
                and _mapping(_mapping(content, "company"), "coverage").get("pages_visited") == 2
            ),
        )
        self._recorder.record(
            "linkedin.companies.get",
            "account_a",
            detail,
            success_detail="search result returned exact Overview and About coverage",
        )

    async def _network_tools(self, names: Mapping[str, str]) -> None:
        listed = await self._collection(
            self._account_a,
            "linkedin.connections.list",
            "account_a",
            base_arguments={"sort_by": "recently_added"},
            item_field="connections",
            identity=lambda item: _string(item, "profile_slug"),
            require_items=True,
        )
        self._recorder.record(
            "linkedin.connections.list",
            "account_a",
            listed.probe,
            success_detail=_collection_detail(listed.probe, listed.items),
        )

        target_name = names.get("account_a")
        if target_name is None:
            self._recorder.skip(
                "linkedin.connections.search",
                "account_a",
                "counterpart profile identity was unavailable",
            )
        else:
            searched = await self._collection(
                self._account_a,
                "linkedin.connections.search",
                "account_a",
                base_arguments={"query": target_name},
                item_field="people",
                identity=lambda item: _string(item, "profile_slug"),
                require_items=True,
            )
            if searched.probe.status is LiveToolStatus.PASSED:
                searched = CollectionProbe(
                    probe=_validate_probe(
                        searched.probe,
                        lambda _content: _require(
                            any(
                                _string(item, "profile_slug").casefold()
                                == self._config.account_b_slug.casefold()
                                for item in searched.items
                            )
                        ),
                    ),
                    items=searched.items,
                )
            self._recorder.record(
                "linkedin.connections.search",
                "account_a",
                searched.probe,
                success_detail="exact counterpart found in first-degree connections",
            )

        invitation_probes: list[Probe] = []
        for direction, invitation_filter in (
            ("received", "focused"),
            ("sent", "people"),
        ):
            page = await self._collection(
                self._account_a,
                "linkedin.invitations.list",
                "account_a",
                base_arguments={
                    "direction": direction,
                    "invitation_filter": invitation_filter,
                },
                item_field="invitations",
                identity=lambda item: _string(item, "invitation_ref"),
                require_items=False,
            )
            invitation_probes.append(page.probe)
        self._recorder.record(
            "linkedin.invitations.list",
            "account_a",
            invitation_probes,
            success_detail="received Focused and sent People views returned bounded pages",
        )

    async def _post_creation(self) -> str | None:
        marker = self._run_id
        text = (
            "LinkedIn MCP weekly validation.\n\n"
            f"Run: {marker}\n"
            "This post is generated by two authorized test accounts to verify the public "
            "MCP tools. No response is needed."
        )
        prepared = await self._recorder.probe(
            self._account_a,
            "linkedin.posts.create.prepare",
            {
                "context_id": self._context("post-create"),
                "request_id": self._request("post-create-prepare"),
                "content": {"mode": "text", "text": text},
                "audience": "anyone",
                "comment_control": "anyone",
            },
        )
        prepared = _validate_prepare(prepared, "post_create")
        self._recorder.record(
            "linkedin.posts.create.prepare",
            "account_a",
            prepared,
            success_detail="immutable text-post preview prepared for the test account",
        )
        execute_arguments = _execute_arguments(
            prepared,
            context_id=self._context("post-create"),
            request_id=self._request("post-create-execute"),
            idempotency_key=f"{self._run_id}-post",
        )
        if execute_arguments is None:
            self._recorder.skip(
                "linkedin.posts.create.execute",
                "account_a",
                "post draft was not safely prepared",
            )
            return None
        executed = await self._recorder.probe(
            self._account_a,
            "linkedin.posts.create.execute",
            execute_arguments,
        )

        post_ref: str | None = None

        def validate_execute(content: dict[str, object]) -> None:
            nonlocal post_ref
            result = _mapping(content, "result")
            _require(result.get("outcome") == "verified" and result.get("performed") is True)
            match = _POST_STATE.fullmatch(_string(result, "final_state"))
            _require(match is not None)
            assert match is not None
            post_ref = match.group("post_ref")

        executed = _validate_probe(executed, validate_execute)
        self._recorder.record(
            "linkedin.posts.create.execute",
            "account_a",
            executed,
            success_detail="LinkedIn visibly verified exactly one published test post",
        )
        return post_ref

    async def _post_read_and_engagement(self, post_ref: str | None) -> None:
        dependent_tools = (
            "linkedin.posts.search",
            "linkedin.posts.get",
            "linkedin.posts.comments.list",
            "linkedin.posts.comment.prepare",
            "linkedin.posts.comment.execute",
            "linkedin.posts.reaction.prepare",
            "linkedin.posts.reaction.execute",
        )
        if post_ref is None:
            for tool in dependent_tools:
                self._recorder.skip(tool, "both", "no verified test post was available")
            return

        post_search = await self._search_created_post(post_ref)
        self._recorder.record(
            "linkedin.posts.search",
            "account_a",
            post_search.probe,
            success_detail="new test post was found through current-member Posts search",
        )

        comment_text = f"Weekly MCP comment validation {self._run_id}. No response is needed."
        comment_prepare = await self._recorder.probe(
            self._account_b,
            "linkedin.posts.comment.prepare",
            {
                "context_id": self._context("post-comment"),
                "request_id": self._request("post-comment-prepare"),
                "post_ref": post_ref,
                "text": comment_text,
            },
        )
        comment_prepare = _validate_prepare(comment_prepare, "comment_create")
        self._recorder.record(
            "linkedin.posts.comment.prepare",
            "account_b",
            comment_prepare,
            success_detail="immutable top-level comment preview prepared on the test post",
        )
        comment_execute_arguments = _execute_arguments(
            comment_prepare,
            context_id=self._context("post-comment"),
            request_id=self._request("post-comment-execute"),
            idempotency_key=f"{self._run_id}-comment",
        )
        if comment_execute_arguments is None:
            self._recorder.skip(
                "linkedin.posts.comment.execute",
                "account_b",
                "comment draft was not safely prepared",
            )
        else:
            comment_execute = await self._recorder.probe(
                self._account_b,
                "linkedin.posts.comment.execute",
                comment_execute_arguments,
            )
            comment_execute = _validate_verified_execute(
                comment_execute,
                final_state_prefix="comment_published:",
            )
            self._recorder.record(
                "linkedin.posts.comment.execute",
                "account_b",
                comment_execute,
                success_detail="LinkedIn visibly verified exactly one top-level comment",
            )

        reaction_prepare = await self._recorder.probe(
            self._account_b,
            "linkedin.posts.reaction.prepare",
            {
                "context_id": self._context("post-reaction"),
                "request_id": self._request("post-reaction-prepare"),
                "post_ref": post_ref,
                "desired_reaction": "like",
            },
        )
        reaction_prepare = _validate_prepare(reaction_prepare, "reaction_set")
        self._recorder.record(
            "linkedin.posts.reaction.prepare",
            "account_b",
            reaction_prepare,
            success_detail="immutable Like-state preview prepared on the test post",
        )
        reaction_execute_arguments = _execute_arguments(
            reaction_prepare,
            context_id=self._context("post-reaction"),
            request_id=self._request("post-reaction-execute"),
            idempotency_key=f"{self._run_id}-reaction",
        )
        if reaction_execute_arguments is None:
            self._recorder.skip(
                "linkedin.posts.reaction.execute",
                "account_b",
                "reaction draft was not safely prepared",
            )
        else:
            reaction_execute = await self._recorder.probe(
                self._account_b,
                "linkedin.posts.reaction.execute",
                reaction_execute_arguments,
            )
            reaction_execute = _validate_verified_execute(
                reaction_execute,
                final_state_prefix="reaction_set:like",
                require_performed=False,
            )
            self._recorder.record(
                "linkedin.posts.reaction.execute",
                "account_b",
                reaction_execute,
                success_detail="LinkedIn visibly verified the requested Like state",
            )

        comments = await self._collection(
            self._account_a,
            "linkedin.posts.comments.list",
            "account_a",
            base_arguments={
                "post_ref": post_ref,
                "sort_by": "most_recent",
                "max_replies_per_comment": 5,
            },
            item_field="threads",
            identity=lambda item: _string(_mapping(item, "comment"), "comment_ref"),
            require_items=True,
        )
        if comments.probe.status is LiveToolStatus.PASSED:
            comments = CollectionProbe(
                probe=_validate_probe(
                    comments.probe,
                    lambda _content: _require(
                        any(
                            _mapping(item, "comment").get("text") == comment_text
                            for item in comments.items
                        )
                    ),
                ),
                items=comments.items,
            )
        self._recorder.record(
            "linkedin.posts.comments.list",
            "account_a",
            comments.probe,
            success_detail="new top-level comment was read back from the discussion",
        )

        detail = await self._recorder.probe(
            self._account_a,
            "linkedin.posts.get",
            {
                "context_id": self._context("post-get"),
                "request_id": self._request("post-get"),
                "post_ref": post_ref,
            },
        )
        detail = _validate_probe(
            detail,
            lambda content: _require(
                _string(_mapping(content, "post"), "post_ref") == post_ref
                and self._run_id in _string(_mapping(content, "post"), "text")
            ),
        )
        self._recorder.record(
            "linkedin.posts.get",
            "account_a",
            detail,
            success_detail="published test post was read back by its exact stable reference",
        )

    async def _search_created_post(self, post_ref: str) -> CollectionProbe:
        attempts: list[Probe] = []
        final_items: tuple[dict[str, object], ...] = ()
        for attempt in range(self._config.post_search_attempts):
            result = await self._collection(
                self._account_a,
                "linkedin.posts.search",
                "account_a",
                base_arguments={
                    "query": "LinkedIn MCP weekly validation",
                    "filters": {
                        "sort_by": "latest",
                        "date_posted": "past_week",
                        "posted_by": ["me"],
                    },
                },
                item_field="posts",
                identity=lambda item: _string(item, "post_ref"),
                require_items=False,
            )
            attempts.append(result.probe)
            final_items = result.items
            if result.probe.status is not LiveToolStatus.PASSED:
                break
            matches = tuple(
                item
                for item in result.items
                if isinstance(item.get("text"), str)
                and self._run_id in cast(str, item["text"])
                and _mapping(item, "author").get("profile_slug") == self._config.account_a_slug
            )
            if len(matches) == 1:
                return CollectionProbe(
                    probe=Probe(
                        status=LiveToolStatus.PASSED,
                        duration_seconds=sum(probe.duration_seconds for probe in attempts),
                        detail=(
                            "created post found through its unique marker and exact author"
                            if _string(matches[0], "post_ref") != post_ref
                            else "created post found through its exact reference and marker"
                        ),
                        calls=sum(probe.calls for probe in attempts),
                        content=result.probe.content,
                    ),
                    items=result.items,
                )
            if attempt + 1 < self._config.post_search_attempts:
                await asyncio.sleep(20)
        if attempts and attempts[-1].status is not LiveToolStatus.PASSED:
            return CollectionProbe(
                probe=_combine_probes(attempts),
                items=final_items,
            )
        return CollectionProbe(
            probe=Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=sum(probe.duration_seconds for probe in attempts),
                detail="bounded Posts search did not find the exact created post",
                calls=sum(probe.calls for probe in attempts),
            ),
            items=final_items,
        )

    async def _messaging_tools(self, names: Mapping[str, str]) -> None:
        message_text = f"Weekly LinkedIn MCP validation {self._run_id}. No response is needed."
        prepared = await self._recorder.probe(
            self._account_a,
            "linkedin.messaging.message.prepare",
            {
                "context_id": self._context("message"),
                "request_id": self._request("message-prepare"),
                "profile_slug": self._config.account_b_slug,
                "message": message_text,
            },
        )
        prepared = _validate_prepare(prepared, "message_send")
        self._recorder.record(
            "linkedin.messaging.message.prepare",
            "account_a",
            prepared,
            success_detail="immutable one-to-one message preview prepared for the counterpart",
        )
        execute_arguments = _execute_arguments(
            prepared,
            context_id=self._context("message"),
            request_id=self._request("message-execute"),
            idempotency_key=f"{self._run_id}-message",
        )
        message_verified = False
        if execute_arguments is None:
            self._recorder.skip(
                "linkedin.messaging.message.execute",
                "account_a",
                "message draft was not safely prepared",
            )
        else:
            executed = await self._recorder.probe(
                self._account_a,
                "linkedin.messaging.message.execute",
                execute_arguments,
            )
            executed = _validate_verified_execute(
                executed,
                final_state_prefix="message_sent",
            )
            self._recorder.record(
                "linkedin.messaging.message.execute",
                "account_a",
                executed,
                success_detail="LinkedIn visibly verified exactly one outgoing message",
            )
            message_verified = executed.status is LiveToolStatus.PASSED

        sender_name = names.get("account_b")
        if sender_name is None:
            self._recorder.skip(
                "linkedin.messaging.search",
                "account_b",
                "sender identity was unavailable",
            )
        else:
            conversations = await self._collection(
                self._account_b,
                "linkedin.messaging.search",
                "account_b",
                base_arguments={"query": sender_name, "category": "focused"},
                item_field="conversations",
                identity=lambda item: _string(item, "conversation_ref"),
                require_items=True,
            )
            self._recorder.record(
                "linkedin.messaging.search",
                "account_b",
                conversations.probe,
                success_detail="counterpart conversation found through current inbox search",
            )

        conversation_probes: list[Probe] = []
        found_message = False
        for attempt in range(3):
            conversation = await self._recorder.probe(
                self._account_b,
                "linkedin.messaging.conversation.get",
                {
                    "context_id": self._context("conversation"),
                    "request_id": self._request("conversation-get"),
                    "profile_slug": self._config.account_a_slug,
                    "max_messages": 20,
                },
            )

            def validate(content: dict[str, object]) -> None:
                nonlocal found_message
                value = _mapping(content, "conversation")
                _require(value.get("is_group") is False)
                messages = _mapping_items(value, "messages")
                found_message = any(message.get("text") == message_text for message in messages)
                if message_verified:
                    _require(found_message)

            conversation = _validate_probe(conversation, validate)
            conversation_probes.append(conversation)
            if (
                conversation.status is not LiveToolStatus.PASSED
                or found_message
                or not message_verified
            ):
                break
            if attempt < 2:
                await asyncio.sleep(10)
        combined = _combine_probes(conversation_probes)
        self._recorder.record(
            "linkedin.messaging.conversation.get",
            "account_b",
            combined,
            success_detail=(
                "counterpart read back the exact newly sent message"
                if message_verified
                else "counterpart conversation history returned through exact profile targeting"
            ),
        )

    async def _collection(
        self,
        session: ClientSession,
        tool: str,
        account: Literal["account_a", "account_b"],
        *,
        base_arguments: Mapping[str, object],
        item_field: str,
        identity: Callable[[dict[str, object]], str],
        require_items: bool,
    ) -> CollectionProbe:
        del account
        context_id = self._context(tool)
        cursor: str | None = None
        probes: list[Probe] = []
        items: list[dict[str, object]] = []
        identities: set[str] = set()
        final_has_more = False
        for page_number in range(1, self._config.max_cursor_pages + 1):
            arguments: dict[str, object] = {
                **base_arguments,
                "context_id": context_id,
                "request_id": self._request(f"{tool}-p{page_number}"),
                "page_size": 5,
            }
            if cursor is not None:
                arguments["cursor"] = cursor
            probe = await self._recorder.probe(session, tool, arguments)
            if probe.status is not LiveToolStatus.PASSED or probe.content is None:
                probes.append(probe)
                break
            try:
                page_items = _mapping_items(probe.content, item_field)
                pagination = _mapping(probe.content, "pagination")
                for item in page_items:
                    item_identity = identity(item)
                    _require(item_identity not in identities)
                    identities.add(item_identity)
                    items.append(item)
                final_has_more = cast(bool, pagination.get("has_more"))
                next_cursor = pagination.get("next_cursor")
                if final_has_more:
                    _require(isinstance(next_cursor, str) and bool(next_cursor))
                    cursor = cast(str, next_cursor)
                else:
                    cursor = None
            except Exception:
                probes.append(
                    Probe(
                        status=LiveToolStatus.FAILED,
                        duration_seconds=probe.duration_seconds,
                        detail="collection response violated pagination or identity invariants",
                        calls=probe.calls,
                    )
                )
                break
            probes.append(probe)
            if not final_has_more:
                break
        combined = _combine_probes(probes)
        if combined.status is LiveToolStatus.PASSED and require_items and not items:
            combined = Probe(
                status=LiveToolStatus.FAILED,
                duration_seconds=combined.duration_seconds,
                detail="collection returned no typed items for the bounded live scenario",
                calls=combined.calls,
            )
        elif combined.status is LiveToolStatus.PASSED:
            ending = "suite safety bound" if final_has_more else "terminal page"
            combined = Probe(
                status=LiveToolStatus.PASSED,
                duration_seconds=combined.duration_seconds,
                detail=f"{len(probes)} disjoint cursor page(s); {ending}",
                calls=combined.calls,
                content=combined.content,
            )
        return CollectionProbe(probe=combined, items=tuple(items))

    def _context(self, suffix: str) -> str:
        normalized = re.sub(r"[^a-z0-9-]+", "-", suffix.casefold()).strip("-")
        return f"{self._run_id}-{normalized}"[:200]

    def _request(self, suffix: str) -> str:
        self._request_counter += 1
        normalized = re.sub(r"[^a-z0-9-]+", "-", suffix.casefold()).strip("-")
        return f"{self._run_id}-{self._request_counter:03d}-{normalized}"[:200]


async def run_live_validation(config: LiveConfiguration) -> LiveValidationReport:
    started_at = utc_now()
    run_id = f"live-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    recorder = LiveRecorder(config)
    config.work_root.mkdir(parents=True, exist_ok=True)
    account_a = _runtime(
        "account_a",
        config.account_a_slug,
        config.account_a_profile_path,
        config.work_root / "account-a",
    )
    account_b = _runtime(
        "account_b",
        config.account_b_slug,
        config.account_b_profile_path,
        config.work_root / "account-b",
        excluded_ports=frozenset({account_a.http_port}),
    )
    try:
        async with (
            _account_session(account_a) as session_a,
            _account_session(account_b) as session_b,
        ):
            await LiveScenario(
                config,
                recorder,
                run_id,
                session_a,
                session_b,
            ).run()
    except Exception as error:
        print(f"live runner stopped safely ({type(error).__name__})", file=sys.stderr)
    report = recorder.finalize(run_id=run_id, started_at=started_at)
    report.write(config.output_path)
    return report


@asynccontextmanager
async def _account_session(runtime: AccountRuntime) -> AsyncGenerator[ClientSession]:
    runtime.work_path.mkdir(parents=True, exist_ok=True)
    environment = _runtime_environment(runtime)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "linkedin_mcp", "serve", "--transport", "stdio"],
        cwd=ROOT,
        env=environment,
    )
    try:
        async with (
            stdio_client(parameters) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            yield session
    finally:
        await _stop_runtime(environment)


def _runtime_environment(runtime: AccountRuntime) -> dict[str, str]:
    return {
        **os.environ,
        "LINKEDIN_MCP_ACCOUNT_ID": runtime.name,
        "LINKEDIN_MCP_BROWSER_PROFILE_PATH": str(runtime.profile_path),
        "LINKEDIN_MCP_ASSET_ROOT_PATH": str(runtime.work_path / "assets"),
        "LINKEDIN_MCP_RUNTIME_LOCK_PATH": str(runtime.work_path / "runtime.lock"),
        "LINKEDIN_MCP_HTTP_HOST": "127.0.0.1",
        "LINKEDIN_MCP_HTTP_PORT": str(runtime.http_port),
        "LINKEDIN_MCP_BROWSER_HEADLESS": "true",
        "LINKEDIN_MCP_BROWSER_AUTO_INSTALL": "false",
        "LINKEDIN_MCP_AUTO_LOGIN_ON_START": "false",
        "LINKEDIN_MCP_MINIMUM_NAVIGATION_INTERVAL_SECONDS": "5",
        "LINKEDIN_MCP_ALLOWED_SCOPES": json.dumps(LIVE_ALLOWED_SCOPES),
        "LINKEDIN_MCP_ALLOWED_EFFECTS": json.dumps(["read", "prepare", "write"]),
        "LINKEDIN_MCP_LOG_LEVEL": "CRITICAL",
    }


async def _stop_runtime(environment: Mapping[str, str]) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "linkedin_mcp",
        "stop",
        "--timeout",
        "20",
        cwd=ROOT,
        env=dict(environment),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(process.wait(), timeout=25)
    except TimeoutError:
        process.terminate()
        await process.wait()


def _runtime(
    name: Literal["account_a", "account_b"],
    slug: str,
    profile_path: Path,
    work_path: Path,
    excluded_ports: frozenset[int] = frozenset(),
) -> AccountRuntime:
    return AccountRuntime(
        name=name,
        slug=slug,
        profile_path=profile_path.resolve(),
        work_path=work_path.resolve(),
        http_port=_available_loopback_port(excluded_ports),
    )


def _available_loopback_port(excluded_ports: frozenset[int] = frozenset()) -> int:
    for _ in range(10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = cast(int, listener.getsockname()[1])
        if port not in excluded_ports:
            return port
    raise RuntimeError("Could not reserve distinct loopback ports for live validation")


def _required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Required live-validation environment is missing: {name}")
    return value


def _validate_profile_directory(path: Path) -> None:
    resolved = path.resolve(strict=False)
    repository = ROOT.resolve()
    if (
        path.is_symlink()
        or not path.is_dir()
        or not any(path.iterdir())
        or resolved == repository
        or repository in resolved.parents
    ):
        raise ValueError(
            "Each live account requires a non-empty, non-symlink Chromium profile "
            "outside the repository checkout"
        )
    if os.name != "nt":
        metadata = path.stat()
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("Each live Chromium profile must deny group and other access")
        if metadata.st_uid != os.getuid():
            raise ValueError("Each live Chromium profile must be owned by the runner user")


def _safe_result_error_code(result: CallToolResult) -> str:
    for block in result.content:
        text = getattr(block, "text", None)
        if not isinstance(text, str):
            continue
        match = _SAFE_ERROR_CODE.search(text)
        if match is not None and match.group(1) in {code.value for code in ErrorCode}:
            return match.group(1)
    return "mcp_tool_error"


def _validate_probe(
    probe: Probe,
    validator: Callable[[dict[str, object]], None],
) -> Probe:
    if probe.status is not LiveToolStatus.PASSED or probe.content is None:
        return probe
    try:
        validator(probe.content)
    except Exception:
        return Probe(
            status=LiveToolStatus.FAILED,
            duration_seconds=probe.duration_seconds,
            detail="MCP result failed the live scenario assertion",
            calls=probe.calls,
        )
    return probe


def _validate_prepare(probe: Probe, action_type: str) -> Probe:
    return _validate_probe(
        probe,
        lambda content: _require(
            content.get("status") == "ready_for_confirmation"
            and _mapping(content, "draft").get("action_type") == action_type
            and _mapping(content, "draft").get("payload_hash")
            == _mapping(content, "approval_preview").get("payload_hash")
        ),
    )


def _validate_verified_execute(
    probe: Probe,
    *,
    final_state_prefix: str,
    require_performed: bool = True,
) -> Probe:
    def validate(content: dict[str, object]) -> None:
        result = _mapping(content, "result")
        _require(result.get("outcome") == "verified")
        if require_performed:
            _require(result.get("performed") is True)
        else:
            _require(result.get("performed") in {True, False})
        _require(_string(result, "final_state").startswith(final_state_prefix))

    return _validate_probe(probe, validate)


def _execute_arguments(
    prepared: Probe,
    *,
    context_id: str,
    request_id: str,
    idempotency_key: str,
) -> dict[str, object] | None:
    if prepared.status is not LiveToolStatus.PASSED or prepared.content is None:
        return None
    draft = _mapping(prepared.content, "draft")
    preview = _mapping(prepared.content, "approval_preview")
    return {
        "context_id": context_id,
        "request_id": request_id,
        "action_id": _string(draft, "action_id"),
        "payload_hash": _string(draft, "payload_hash"),
        "approval_preview": preview,
        "idempotency_key": idempotency_key,
    }


def _mapping(parent: Mapping[str, object], key: str) -> dict[str, object]:
    return _DICT_ADAPTER.validate_python(parent[key])


def _mapping_items(parent: Mapping[str, object], key: str) -> list[dict[str, object]]:
    values = _LIST_ADAPTER.validate_python(parent[key])
    return [_DICT_ADAPTER.validate_python(value) for value in values]


def _string(parent: Mapping[str, object], key: str) -> str:
    value = parent[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected a non-empty string at {key}")
    return value


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Live scenario assertion failed")


def _combine_probes(probes: Sequence[Probe]) -> Probe:
    if not probes:
        return Probe(
            status=LiveToolStatus.FAILED,
            duration_seconds=0,
            detail="live scenario made no MCP call",
            calls=0,
        )
    status = max(probes, key=lambda probe: LIVE_STATUS_ORDER[probe.status.value]).status
    failing = next((probe for probe in probes if probe.status is status), probes[-1])
    return Probe(
        status=status,
        duration_seconds=sum(probe.duration_seconds for probe in probes),
        detail=failing.detail,
        calls=sum(probe.calls for probe in probes),
        content=probes[-1].content if status is LiveToolStatus.PASSED else None,
    )


def _collection_detail(probe: Probe, items: Sequence[dict[str, object]]) -> str:
    if probe.status is not LiveToolStatus.PASSED:
        return probe.detail
    return f"returned {len(items)} unique typed item(s); {probe.detail}"


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run opt-in LinkedIn MCP live validation")
    value.add_argument("--output", type=Path, default=None)
    return value


def _startup_failure_report(output_path: Path) -> LiveValidationReport:
    started = utc_now()
    run_id = f"live-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    results = tuple(
        LiveToolResult(
            tool=tool,
            status=(
                LiveToolStatus.SIMULATOR_ONLY
                if tool in INVITATION_MUTATION_TOOLS
                else LiveToolStatus.BLOCKED
            ),
            account="none",
            calls=0,
            duration_seconds=0,
            detail=(
                "excluded from the stable two-account live loop"
                if tool in INVITATION_MUTATION_TOOLS
                else "live runner configuration or profile was unavailable"
            ),
        )
        for tool in MOCK_VERIFICATION
    )
    report = LiveValidationReport(
        run_id=run_id,
        started_at=started,
        completed_at=utc_now(),
        overall_status="failed",
        tool_results=results,
    )
    report.write(output_path)
    return report


def main() -> None:
    arguments = parser().parse_args()
    output_override = cast(Path | None, arguments.output)
    try:
        config = LiveConfiguration.from_environment(output_override)
        report = asyncio.run(run_live_validation(config))
    except Exception as error:
        if output_override is not None:
            _startup_failure_report(output_override)
        print(f"live validation could not start safely ({type(error).__name__})", file=sys.stderr)
        raise SystemExit(2) from error
    raise SystemExit(0 if report.overall_status == "passed" else 1)


if __name__ == "__main__":
    main()
