from __future__ import annotations

from pathlib import Path

from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.container import create_production_container
from linkedin_mcp.domain.models import (
    CapabilityName,
    CompanySearchFilters,
    ConnectionsSearchFilters,
    JobSearchFilters,
    PeopleSearchFilters,
    PersonProfileSectionSelector,
    PostCreateMode,
    PostSearchFilters,
    ReactionState,
    StrictModel,
)
from linkedin_mcp.errors import ErrorCode
from linkedin_mcp.server import create_mcp_server
from tests.simulator import standard_scenario
from tests.verification_manifest import MOCK_VERIFICATION, missing_test_files

ROOT = Path(__file__).parents[2]

EXPECTED_FILTER_FIELDS: dict[type[StrictModel], frozenset[str]] = {
    JobSearchFilters: frozenset(
        {
            "sort_by",
            "location_geo_id",
            "distance_miles",
            "workplace_types",
            "experience_levels",
            "employment_types",
            "location_ids",
            "location_names",
            "company_ids",
            "company_names",
            "industry_ids",
            "industry_names",
            "job_function_ids",
            "job_function_names",
            "job_title_ids",
            "job_title_names",
            "benefits",
            "commitments",
            "easy_apply_only",
            "has_verifications",
            "under_10_applicants",
            "in_your_network",
            "fair_chance_employer",
        }
    ),
    PeopleSearchFilters: frozenset(
        {
            "connection_degrees",
            "actively_hiring",
            "actively_hiring_job_title_ids",
            "actively_hiring_job_title_names",
            "location_ids",
            "location_names",
            "current_company_ids",
            "current_company_names",
            "connections_of_ids",
            "connections_of_names",
            "followers_of_ids",
            "followers_of_names",
            "past_company_ids",
            "past_company_names",
            "school_ids",
            "school_names",
            "industry_ids",
            "industry_names",
            "profile_language_ids",
            "profile_language_names",
            "service_category_ids",
            "service_category_names",
            "first_name",
            "last_name",
            "title",
            "company",
            "school",
        }
    ),
    ConnectionsSearchFilters: frozenset(
        {
            "actively_hiring",
            "actively_hiring_job_title_ids",
            "actively_hiring_job_title_names",
            "location_ids",
            "location_names",
            "current_company_ids",
            "current_company_names",
            "connections_of_ids",
            "connections_of_names",
            "followers_of_ids",
            "followers_of_names",
            "past_company_ids",
            "past_company_names",
            "school_ids",
            "school_names",
            "industry_ids",
            "industry_names",
            "profile_language_ids",
            "profile_language_names",
            "service_category_ids",
            "service_category_names",
            "first_name",
            "last_name",
            "title",
            "company",
            "school",
        }
    ),
    CompanySearchFilters: frozenset(
        {
            "location_ids",
            "location_names",
            "industry_ids",
            "industry_names",
            "company_sizes",
            "has_job_listings",
            "has_first_degree_connections",
        }
    ),
    PostSearchFilters: frozenset(
        {
            "sort_by",
            "date_posted",
            "content_type",
            "from_member_ids",
            "from_member_names",
            "from_company_ids",
            "from_company_names",
            "posted_by",
            "mentioning_member_ids",
            "mentioning_member_names",
            "mentioning_company_ids",
            "mentioning_company_names",
            "author_industry_ids",
            "author_industry_names",
            "author_company_ids",
            "author_company_names",
            "author_keywords",
        }
    ),
}

EXPECTED_PERSON_SECTIONS = frozenset(
    {
        "all",
        "overview",
        "about",
        "experience",
        "education",
        "licenses-certifications",
        "projects",
        "volunteering",
        "skills",
        "interests",
        "featured",
        "courses",
        "honors-awards",
        "languages",
        "organizations",
        "publications",
        "patents",
        "recommendations",
        "test-scores",
    }
)
EXPECTED_REACTIONS = frozenset(
    {"none", "like", "celebrate", "support", "love", "insightful", "funny"}
)
EXPECTED_POST_CREATE_MODES = frozenset(
    {
        "text",
        "images",
        "video",
        "document",
        "poll",
        "celebration",
        "event",
        "hiring",
        "expert_request",
    }
)
EXPECTED_ERROR_CODES = frozenset(
    {
        "configuration_error",
        "access_paused",
        "authentication_required",
        "idempotency_conflict",
        "invalid_cursor",
        "invalid_target",
        "restriction_detected",
        "parser_drift",
        "browser_unavailable",
        "internal_error",
    }
)


def test_manifest_matches_the_exact_public_tool_surface() -> None:
    container = create_production_container(Settings())
    mcp = create_mcp_server(container)
    tools = mcp._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    registered_names = {tool.name for tool in tools}

    assert registered_names == set(MOCK_VERIFICATION)
    assert {descriptor.name.value for descriptor in create_default_registry().list()} == {
        name
        for name in MOCK_VERIFICATION
        if name
        not in {
            "linkedin.server.status",
            "linkedin.capabilities.list",
            "linkedin.session.status",
        }
    }
    assert {name.value for name in CapabilityName} <= registered_names


def test_public_tools_do_not_expose_browser_queue_or_pacing_controls() -> None:
    container = create_production_container(Settings())
    mcp = create_mcp_server(container)
    tools = mcp._tool_manager.list_tools()  # pyright: ignore[reportPrivateUsage]
    forbidden_top_level_arguments = {
        "browser",
        "click",
        "interval",
        "javascript",
        "navigation",
        "pacing",
        "queue",
        "scrape_delay",
        "selector",
        "url",
    }

    assert not any(
        token in tool.name
        for tool in tools
        for token in (".browser.", ".click.", ".javascript.", ".navigate.", ".network.")
    )
    for tool in tools:
        properties = tool.parameters.get("properties", {})
        assert forbidden_top_level_arguments.isdisjoint(properties), tool.name


def test_every_manifest_entry_has_real_layer_ownership_and_existing_tests() -> None:
    assert missing_test_files(ROOT) == ()
    for name, verification in MOCK_VERIFICATION.items():
        assert "contract" in verification.layers, name
        assert "runtime" in verification.layers, name
        if verification.effect == "write":
            assert {"page", "action", "workflow"} <= verification.layers, name
        assert verification.test_files, name


def test_filter_and_selector_inventory_cannot_grow_silently() -> None:
    for model, expected_fields in EXPECTED_FILTER_FIELDS.items():
        assert frozenset(model.model_fields) == expected_fields

    assert {item.value for item in PersonProfileSectionSelector} == EXPECTED_PERSON_SECTIONS
    assert {item.value for item in PostCreateMode} == EXPECTED_POST_CREATE_MODES
    assert {item.value for item in ReactionState} == EXPECTED_REACTIONS
    assert {item.value for item in ErrorCode} == EXPECTED_ERROR_CODES


def test_mock_verification_provenance_is_explicitly_synthetic() -> None:
    scenario = standard_scenario()

    assert scenario.provenance.source == "synthetic"
    assert scenario.provenance.recorded_at is None
    assert scenario.provenance.schema_version == "1"
