"""Climate platform for Habitat PTAC thermostats."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    FAN_MODE,
    FAN_MODE_AUTO,
    FAN_MODE_HIGH,
    FAN_MODE_LOW,
    HEATING_SETPOINT,
    LOCAL_TEMPERATURE,
    MAX_HEATING_SETPOINT,
    MIN_HEATING_SETPOINT,
    PTAC_ERROR_CODE,
    RUNNING_STATE,
    SET_FAN_MODE,
    SET_HEATING_SETPOINT,
    SET_SYSTEM_MODE,
    SYSTEM_MODE,
    SYSTEM_MODE_COOL,
    SYSTEM_MODE_FAN_ONLY,
    SYSTEM_MODE_HEAT,
    SYSTEM_MODE_OFF,
)
from .coordinator import HabitatCoordinator
from .entity import HabitatEntity

SYSTEM_MODE_TO_HVAC = {
    SYSTEM_MODE_OFF: HVACMode.OFF,
    SYSTEM_MODE_COOL: HVACMode.COOL,
    SYSTEM_MODE_HEAT: HVACMode.HEAT,
    SYSTEM_MODE_FAN_ONLY: HVACMode.FAN_ONLY,
}
HVAC_TO_SYSTEM_MODE = {hvac: mode for mode, hvac in SYSTEM_MODE_TO_HVAC.items()}
FAN_MODE_TO_HA = {FAN_MODE_LOW: FAN_LOW, FAN_MODE_HIGH: FAN_HIGH, FAN_MODE_AUTO: FAN_AUTO}
HA_TO_FAN_MODE = {ha: mode for mode, ha in FAN_MODE_TO_HA.items()}

# RunningState looks like the Zigbee thermostat running-state bitmap (unconfirmed; 32 seen while in fan-only)
RUNNING_HEAT_BITS = 0x01 | 0x08
RUNNING_COOL_BITS = 0x02 | 0x10
RUNNING_FAN_BITS = 0x04 | 0x20 | 0x40

# Limits reported by the thermostat when it has not reported its own (°C)
DEFAULT_MIN_CELSIUS = 5.0
DEFAULT_MAX_CELSIUS = 35.0


def celsius_x100_to_fahrenheit(value: int | None) -> float | None:
    """Convert a °C×100 shadow value to °F."""
    if value is None:
        return None
    return round(TemperatureConverter.convert(value / 100, UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT), 1)


def fahrenheit_to_celsius_x100(value: float) -> int:
    """Convert °F to a °C×100 shadow value (73°F -> 2278, as the app sends)."""
    return round(TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS) * 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Habitat PTAC thermostats."""
    coordinator: HabitatCoordinator = entry.runtime_data
    async_add_entities(HabitatClimate(coordinator, device) for device in coordinator.data.values())


class HabitatClimate(HabitatEntity, ClimateEntity):
    """Habitat PTAC thermostat.

    The thermostat works in °C×100 but the app steps in whole °F, so the entity is °F-native with a 1° step;
    Home Assistant converts for metric installs.
    """

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 1.0
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes: ClassVar[list[HVACMode]] = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY]
    _attr_fan_modes: ClassVar[list[str]] = [FAN_AUTO, FAN_LOW, FAN_HIGH]

    def __init__(self, coordinator: HabitatCoordinator, device: Any) -> None:
        """Initialize the thermostat."""
        super().__init__(coordinator, device)
        # Mode restored by turn_on; updated whenever the thermostat reports a mode other than off
        self._last_active_mode = HVACMode.COOL
        self._remember_active_mode()

    def _remember_active_mode(self) -> None:
        if (mode := self.hvac_mode) not in (None, HVACMode.OFF):
            self._last_active_mode = mode

    @callback
    def _handle_coordinator_update(self) -> None:
        self._remember_active_mode()
        super()._handle_coordinator_update()

    @property
    def current_temperature(self) -> float | None:
        """Return the measured temperature."""
        return celsius_x100_to_fahrenheit(self.properties.get(LOCAL_TEMPERATURE))

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature (one setpoint in every mode)."""
        return celsius_x100_to_fahrenheit(self.properties.get(HEATING_SETPOINT))

    @property
    def min_temp(self) -> float:
        """Return the lowest settable temperature."""
        return celsius_x100_to_fahrenheit(self.properties.get(MIN_HEATING_SETPOINT, DEFAULT_MIN_CELSIUS * 100))

    @property
    def max_temp(self) -> float:
        """Return the highest settable temperature."""
        return celsius_x100_to_fahrenheit(self.properties.get(MAX_HEATING_SETPOINT, DEFAULT_MAX_CELSIUS * 100))

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return the system mode."""
        return SYSTEM_MODE_TO_HVAC.get(self.properties.get(SYSTEM_MODE))

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return what the unit is doing right now."""
        if (mode := self.hvac_mode) is None:
            return None
        if mode == HVACMode.OFF:
            return HVACAction.OFF
        running_state = self.properties.get(RUNNING_STATE)
        if running_state is None:
            return None
        if running_state & RUNNING_HEAT_BITS:
            return HVACAction.HEATING
        if running_state & RUNNING_COOL_BITS:
            return HVACAction.COOLING
        if running_state & RUNNING_FAN_BITS:
            return HVACAction.FAN
        return HVACAction.IDLE

    @property
    def fan_mode(self) -> str | None:
        """Return the fan speed."""
        return FAN_MODE_TO_HA.get(self.properties.get(FAN_MODE))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return raw values that are not mapped yet."""
        properties = self.properties
        return {
            name: properties[key]
            for name, key in (("running_state", RUNNING_STATE), ("error_code", PTAC_ERROR_CODE))
            if key in properties
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_send(
                self._thing, {SET_HEATING_SETPOINT: fahrenheit_to_celsius_x100(temperature)}
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the system mode."""
        await self.coordinator.async_send(self._thing, {SET_SYSTEM_MODE: HVAC_TO_SYSTEM_MODE[hvac_mode]})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan speed."""
        await self.coordinator.async_send(self._thing, {SET_FAN_MODE: HA_TO_FAN_MODE[fan_mode]})

    async def async_turn_on(self) -> None:
        """Turn on in the last mode used."""
        await self.async_set_hvac_mode(self._last_active_mode)

    async def async_turn_off(self) -> None:
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
