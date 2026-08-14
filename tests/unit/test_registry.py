from __future__ import annotations

from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.domain.models import CapabilityEffect, CapabilityName, LinkedInSurface


def test_registry_has_one_enabled_descriptor_for_every_capability() -> None:
    registry = create_default_registry()
    descriptors = registry.list()

    assert {descriptor.name for descriptor in descriptors} == set(CapabilityName)
    assert len(descriptors) == 21
    for descriptor in descriptors:
        info = descriptor.info()
        assert info.enabled is True
        assert info.name is descriptor.name
        assert info.effect is descriptor.effect


def test_registry_exposes_seven_atomic_write_tools() -> None:
    registry = create_default_registry()
    writes = {
        descriptor.name: descriptor
        for descriptor in registry.list()
        if descriptor.effect is CapabilityEffect.WRITE
    }

    assert set(writes) == {
        CapabilityName.POSTS_CREATE,
        CapabilityName.POST_COMMENT,
        CapabilityName.POST_REACT,
        CapabilityName.INVITATION_SEND,
        CapabilityName.INVITATION_ACCEPT,
        CapabilityName.INVITATION_IGNORE,
        CapabilityName.MESSAGING_SEND,
    }
    assert writes[CapabilityName.POSTS_CREATE].required_surfaces == frozenset(
        {LinkedInSurface.POST_COMPOSER}
    )
    assert writes[CapabilityName.MESSAGING_SEND].required_surfaces == frozenset(
        {
            LinkedInSurface.MESSAGING,
            LinkedInSurface.MEMBER_PROFILE,
        }
    )


def test_registry_rejects_duplicate_and_unknown_names() -> None:
    registry = create_default_registry()
    descriptor = registry.get(CapabilityName.JOBS_SEARCH)
    assert descriptor.name is CapabilityName.JOBS_SEARCH
