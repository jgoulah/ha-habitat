"""Tests for the config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.habitat_homelink.api import HabitatAuthenticationError
from custom_components.habitat_homelink.const import DOMAIN

from .fixtures import FakeApi


async def test_user_flow(hass: HomeAssistant) -> None:
    with (
        patch("custom_components.habitat_homelink.config_flow.HabitatApi", FakeApi),
        patch("custom_components.habitat_homelink.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "Me@Example.com", CONF_PASSWORD: "pw"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Habitat (Me@Example.com)"
    assert result["result"].unique_id == "me@example.com"


async def test_invalid_auth(hass: HomeAssistant) -> None:
    class RejectingApi(FakeApi):
        async def authenticate(self) -> None:
            raise HabitatAuthenticationError("nope")

    with patch("custom_components.habitat_homelink.config_flow.HabitatApi", RejectingApi):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "bad"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
