"""Synthetic fixture routing and provenance for the semantic site simulator."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from tests.simulator.state import SimulatorState

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "linkedin"


def _empty_variants() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class FixtureProvenance:
    source: str = "synthetic"
    schema_version: str = "1"
    recorded_at: str | None = None


@dataclass(slots=True)
class SimulatorScenario:
    scenario_id: str
    state: SimulatorState
    provenance: FixtureProvenance = field(default_factory=FixtureProvenance)
    variants: dict[str, str] = field(default_factory=_empty_variants)

    def use_fixture(self, surface: str, fixture_name: str) -> None:
        path = FIXTURE_ROOT / fixture_name
        if not path.is_file():
            raise ValueError(f"Unknown simulator fixture: {fixture_name}")
        self.variants[surface] = fixture_name

    def fixture_for_url(self, url: str) -> Path:
        path = urlsplit(url).path
        surface, default_fixture = self._route(path)
        fixture_name = self.variants.get(surface, default_fixture)
        fixture = FIXTURE_ROOT / fixture_name
        if not fixture.is_file():
            raise ValueError(f"Simulator surface {surface!r} has no fixture {fixture_name!r}.")
        return fixture

    def surface_for_url(self, url: str) -> str:
        surface, _ = self._route(urlsplit(url).path)
        return surface

    @staticmethod
    def _route(path: str) -> tuple[str, str]:
        if path.startswith("/jobs/search"):
            return "jobs.search", "jobs/latest/search.html"
        if path.startswith("/jobs/view/"):
            return "jobs.get", "jobs/latest/detail-easy-apply.html"
        if path.startswith("/search/results/people"):
            return "people.search", "people/latest/search.html"
        if "/details/experience" in path:
            return "people.experience", "people/latest/experience.html"
        if "/details/education" in path:
            return "people.education", "people/latest/education.html"
        if "/details/skills" in path:
            return "people.skills", "people/latest/skills.html"
        if path.startswith("/in/"):
            return "people.get", "people/latest/overview-complete.html"
        if path.startswith("/search/results/companies"):
            return "companies.search", "companies/latest/search.html"
        if path.endswith("/about/"):
            return "companies.about", "companies/latest/about.html"
        if path.startswith("/company/"):
            return "companies.get", "companies/latest/overview.html"
        if path.startswith("/search/results/content"):
            return "posts.search", "posts/latest/search.html"
        if path.startswith("/feed/update/"):
            return "posts.get", "posts/latest/detail-image.html"
        if path.startswith("/mynetwork/invitation-manager/sent"):
            return (
                "invitations.sent.people",
                "invitations/latest/sent-people.html",
            )
        if path.startswith("/mynetwork/invitation-manager"):
            return (
                "invitations.received.all",
                "invitations/latest/received-all.html",
            )
        if path.startswith("/mynetwork/invite-connect/connections"):
            return "connections.list", "connections/latest/list.html"
        if path.startswith("/messaging"):
            return "messaging", "messaging/latest/current.html"
        if path in {"/feed", "/feed/"}:
            return "posts.create", "posts/latest/composer.html"
        raise ValueError(f"The simulator has no registered surface for {path!r}.")


def standard_scenario() -> SimulatorScenario:
    return SimulatorScenario(
        scenario_id="standard-synthetic-linkedin",
        state=SimulatorState.standard(),
    )
