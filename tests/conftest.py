"""Shared fixtures for the Neatsvor S600 tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture
def client_cls():
    """Patch the MQTT client used by the coordinator (connected by default)."""
    with patch("custom_components.neatsvor_s600.coordinator.NeatsvorMqttClient") as cls:
        cls.return_value.is_connected.return_value = True
        yield cls


@pytest.fixture
def api_cls():
    """Patch the REST client built in async_setup_entry."""
    with patch("custom_components.neatsvor_s600.NeatsvorApiClient") as cls:
        cls.return_value.login = AsyncMock(return_value="new-token")
        cls.return_value.set_token = MagicMock()
        yield cls
