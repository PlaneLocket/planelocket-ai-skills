"""Use real Home Assistant fixtures; never connect to household services."""

import json
from pathlib import Path

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.planelocket_ai.const import DOMAIN


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow HA's loader to discover this test checkout."""


@pytest.fixture
def entry():
    """A synthetic credential, never a production token."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PlaneLocket AI",
        data={"url": "https://ai.example.test", "token": "test-only-credential"},
        version=1,
    )


@pytest.fixture
def evidence():
    return json.loads((Path(__file__).parent / "fixtures/harrison_ford.json").read_text())
