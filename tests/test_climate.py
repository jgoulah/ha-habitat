"""Tests for the PTAC climate entity, set up through the config entry with a fake cloud."""

from __future__ import annotations

import functools
from unittest.mock import patch

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitat_homelink.climate import celsius_x100_to_fahrenheit, fahrenheit_to_celsius_x100
from custom_components.habitat_homelink.const import DOMAIN
from custom_components.habitat_homelink.coordinator import HabitatCoordinator

from .fixtures import INDEX, THERMOSTAT, FakeApi, FakeConnection

ENTITY_ID = "climate.habitat_ptac"


@pytest.mark.parametrize(("fahrenheit", "celsius_x100"), [(72, 2222), (73, 2278), (74, 2333)])
def test_conversion_matches_app(fahrenheit: int, celsius_x100: int) -> None:
    assert fahrenheit_to_celsius_x100(fahrenheit) == celsius_x100
    assert round(celsius_x100_to_fahrenheit(celsius_x100)) == fahrenheit


@pytest.fixture
async def connection(hass: HomeAssistant) -> FakeConnection:
    """Set up the integration and return its fake MQTT connection."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    FakeConnection.instances.clear()
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_EMAIL: "a@b.c", CONF_PASSWORD: "x"}, unique_id="a@b.c")
    entry.add_to_hass(hass)
    with (
        patch("custom_components.habitat_homelink.HabitatApi", FakeApi),
        patch(
            "custom_components.habitat_homelink.HabitatCoordinator",
            functools.partial(HabitatCoordinator, connection_factory=FakeConnection),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return FakeConnection.instances[-1]


async def test_state(hass: HomeAssistant, connection: FakeConnection) -> None:
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_TEMPERATURE] == 74.0
    assert state.attributes["current_temperature"] == 73.6
    assert state.attributes[ATTR_FAN_MODE] == "auto"
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE
    assert state.attributes["min_temp"] == 41.0 and state.attributes["max_temp"] == 95.0
    assert connection.things == [THERMOSTAT]
    assert hass.states.get("sensor.habitat_ptac_filter_run_days").state == "12"


async def test_commands(hass: HomeAssistant, connection: FakeConnection) -> None:
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_temperature", {ATTR_ENTITY_ID: ENTITY_ID, ATTR_TEMPERATURE: 73}, blocking=True
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_hvac_mode", {ATTR_ENTITY_ID: ENTITY_ID, ATTR_HVAC_MODE: HVACMode.FAN_ONLY}, blocking=True
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN, "set_fan_mode", {ATTR_ENTITY_ID: ENTITY_ID, ATTR_FAN_MODE: "low"}, blocking=True
    )
    assert connection.published == [
        (THERMOSTAT, INDEX, {"ep0:sPTAC868:SetHeatingSetpoint_x100": 2278}),
        (THERMOSTAT, INDEX, {"ep0:sPTAC868:SetSystemMode": 7}),
        (THERMOSTAT, INDEX, {"ep0:sPTAC868:SetFanMode": 1}),
    ]
    # Commanded values show until the thermostat reports them
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.FAN_ONLY
    assert state.attributes[ATTR_TEMPERATURE] == 73.0
    assert state.attributes[ATTR_FAN_MODE] == "low"


async def test_turn_on_restores_last_mode(hass: HomeAssistant, connection: FakeConnection) -> None:
    await hass.services.async_call(CLIMATE_DOMAIN, "turn_off", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    await hass.services.async_call(CLIMATE_DOMAIN, "turn_on", {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True)
    assert [properties for _, _, properties in connection.published] == [
        {"ep0:sPTAC868:SetSystemMode": 0},
        {"ep0:sPTAC868:SetSystemMode": 3},
    ]


async def test_pushed_update(hass: HomeAssistant, connection: FakeConnection) -> None:
    connection.push(
        THERMOSTAT,
        {
            "state": {
                "reported": {
                    "connected": "true",
                    INDEX: {"properties": {"ep0:sPTAC868:SystemMode": 4, "ep0:sPTAC868:RunningState": 1}},
                }
            }
        },
    )
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY_ID)
    assert state.state == HVACMode.HEAT
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    assert state.attributes[ATTR_TEMPERATURE] == 74.0  # untouched properties are kept


async def test_refresh_requested_on_connect(hass: HomeAssistant, connection: FakeConnection) -> None:
    connection.kwargs["on_connected"]()
    await hass.async_block_till_done()
    assert connection.published == [(THERMOSTAT, INDEX, {"ep0:sPTAC868:SetRefresh": "040000"})]
