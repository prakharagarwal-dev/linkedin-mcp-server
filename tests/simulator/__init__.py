"""Offline, synthetic LinkedIn simulator used only by the test suite."""

from tests.simulator.browser import SimulatorBrowser
from tests.simulator.scenario import FixtureProvenance, SimulatorScenario, standard_scenario
from tests.simulator.state import (
    SimulatorAction,
    SimulatorCompany,
    SimulatorConversation,
    SimulatorFault,
    SimulatorJob,
    SimulatorMessage,
    SimulatorPerson,
    SimulatorPost,
    SimulatorState,
)

__all__ = [
    "FixtureProvenance",
    "SimulatorAction",
    "SimulatorBrowser",
    "SimulatorCompany",
    "SimulatorConversation",
    "SimulatorFault",
    "SimulatorJob",
    "SimulatorMessage",
    "SimulatorPerson",
    "SimulatorPost",
    "SimulatorScenario",
    "SimulatorState",
    "standard_scenario",
]
