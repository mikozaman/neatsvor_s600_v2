"""Shared fixtures for the Neatsvor S600 tests."""
from __future__ import annotations

import pytest
from custom_components.neatsvor_s600.const import DOMAIN
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"

MOCK_MAC = "12-34-56-78-9A-BC"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load the integration from custom_components."""
    yield


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Config entry for a configured robot."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Neatsvor S600 ({MOCK_MAC})",
        unique_id=MOCK_MAC,
        data={"mac": MOCK_MAC, "email": "user@example.com", "app_token": "tok"},
    )
