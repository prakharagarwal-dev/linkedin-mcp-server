from __future__ import annotations

import pytest

from linkedin_mcp.errors import InvalidTargetError
from linkedin_mcp.tools._shared.urls import (
    canonical_company_url,
    canonical_conversation_url,
    canonical_job_url,
    canonical_post_url,
    canonical_profile_url,
    comment_reference_from_value,
    company_slug_from_url,
    conversation_id_from_url,
    job_id_from_url,
    post_reference_from_comment_ref,
    post_reference_from_value,
    profile_slug_from_url,
    validate_linkedin_url,
)


def test_job_ids_are_extracted_from_supported_urls() -> None:
    assert job_id_from_url("https://www.linkedin.com/jobs/view/123456789/") == "123456789"
    assert (
        job_id_from_url(
            "https://www.linkedin.com/jobs/search/?keywords=python&currentJobId=987654321"
        )
        == "987654321"
    )


def test_linkedin_url_policy_requires_exact_host() -> None:
    with pytest.raises(InvalidTargetError):
        validate_linkedin_url(
            "https://www.linkedin.com.attacker.example/jobs/view/123456/",
            ("www.linkedin.com",),
        )


def test_canonical_job_url_rejects_non_numeric_ids() -> None:
    with pytest.raises(InvalidTargetError):
        canonical_job_url("abc")


def test_profile_slugs_are_extracted_and_canonicalized() -> None:
    assert profile_slug_from_url("https://www.linkedin.com/in/jane-doe/") == "jane-doe"
    assert (
        profile_slug_from_url("https://www.linkedin.com/in/jane-doe/details/experience/")
        == "jane-doe"
    )
    assert canonical_profile_url("jane-doe") == "https://www.linkedin.com/in/jane-doe/"
    assert profile_slug_from_url("https://www.linkedin.com/in/fixture-member-/") == (
        "fixture-member-"
    )
    assert (
        profile_slug_from_url("https://www.linkedin.com/in/fixture-member--/") == "fixture-member--"
    )
    assert canonical_profile_url("another-fixture-") == (
        "https://www.linkedin.com/in/another-fixture-/"
    )


@pytest.mark.parametrize("slug", ("ab", "-jane", "jane_doe", "a" * 201))
def test_canonical_profile_url_rejects_invalid_slugs(slug: str) -> None:
    with pytest.raises(InvalidTargetError):
        canonical_profile_url(slug)


def test_company_slugs_are_extracted_and_canonicalized() -> None:
    assert (
        company_slug_from_url("https://www.linkedin.com/company/acme-cloud/about/") == "acme-cloud"
    )
    assert canonical_company_url("acme-cloud") == ("https://www.linkedin.com/company/acme-cloud/")
    assert canonical_company_url("acme-cloud", "about") == (
        "https://www.linkedin.com/company/acme-cloud/about/"
    )


@pytest.mark.parametrize("slug", ("-acme", "acme-", "acme_cloud", "a" * 201))
def test_canonical_company_url_rejects_invalid_slugs(slug: str) -> None:
    with pytest.raises(InvalidTargetError):
        canonical_company_url(slug)


def test_canonical_company_url_rejects_unregistered_sections() -> None:
    with pytest.raises(InvalidTargetError):
        canonical_company_url("acme-cloud", "products")


def test_post_and_comment_references_are_stable_and_canonicalized() -> None:
    activity_id = "7312345678901234567"
    assert post_reference_from_value(f"urn:li:activity:{activity_id}") == f"activity:{activity_id}"
    assert (
        post_reference_from_value(f"https://www.linkedin.com/posts/jane_activity-{activity_id}-x")
        == f"activity:{activity_id}"
    )
    assert (
        post_reference_from_value(
            f"https://www.linkedin.com/posts/jane-123_python-share-{activity_id}-x/"
        )
        == f"share:{activity_id}"
    )
    assert (
        post_reference_from_value(
            f"https://www.linkedin.com/posts/jane_python-ugcPost-{activity_id}-x/"
        )
        == f"ugc-post:{activity_id}"
    )
    assert post_reference_from_value(f"urn:li:ugcPost:{activity_id}") == f"ugc-post:{activity_id}"
    assert post_reference_from_value(f"urn:li:share:{activity_id}") == f"share:{activity_id}"
    assert canonical_post_url(f"share:{activity_id}") == (
        f"https://www.linkedin.com/feed/update/urn:li:share:{activity_id}/"
    )
    assert canonical_post_url(f"activity:{activity_id}") == (
        f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"
    )
    comment_ref = f"comment:activity:{activity_id}:111"
    assert (
        comment_reference_from_value(f"urn:li:comment:(activity:{activity_id},111)") == comment_ref
    )
    assert (
        comment_reference_from_value(
            f"replaceableComment_urn:li:comment:(urn:li:activity:{activity_id},111)"
        )
        == comment_ref
    )
    assert post_reference_from_comment_ref(comment_ref) == f"activity:{activity_id}"


@pytest.mark.parametrize(
    "post_ref",
    (
        "activity:not-digits",
        "ugcPost:731234",
        "post:731234",
        "share:1234",
        "activity:1234",
    ),
)
def test_canonical_post_url_rejects_invalid_references(post_ref: str) -> None:
    with pytest.raises(InvalidTargetError):
        canonical_post_url(post_ref)


def test_comment_reference_rejects_cross_surface_values() -> None:
    assert comment_reference_from_value("urn:li:activity:7312345678901234567") is None
    with pytest.raises(InvalidTargetError):
        post_reference_from_comment_ref("comment:invalid")


def test_conversation_ids_are_extracted_and_canonicalized() -> None:
    conversation_id = "2-abc_DEF%3D"

    assert (
        conversation_id_from_url(
            f"https://www.linkedin.com/messaging/thread/{conversation_id}/?foo=bar"
        )
        == conversation_id
    )
    assert (
        canonical_conversation_url(conversation_id)
        == f"https://www.linkedin.com/messaging/thread/{conversation_id}/"
    )
    assert conversation_id_from_url("https://www.linkedin.com/messaging/") is None


@pytest.mark.parametrize("conversation_id", ("ab", "contains/slash", "space value", "a" * 501))
def test_canonical_conversation_url_rejects_unsafe_ids(conversation_id: str) -> None:
    with pytest.raises(InvalidTargetError):
        canonical_conversation_url(conversation_id)
