"""Sensor platform for Habitat PTAC thermostats."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import FILTER_DAYS, FILTER_RUN_DAYS
from .coordinator import HabitatCoordinator, HabitatDevice
from .entity import HabitatEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Habitat sensors."""
    coordinator: HabitatCoordinator = entry.runtime_data
    async_add_entities(HabitatFilterSensor(coordinator, device) for device in coordinator.data.values())


class HabitatFilterSensor(HabitatEntity, SensorEntity):
    """Days the filter has been running, with the cleaning interval as an attribute."""

    _attr_translation_key = "filter_run_days"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HabitatCoordinator, device: HabitatDevice) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device, "filter_run_days")

    @property
    def native_value(self) -> int | None:
        """Return days since the filter was last reset."""
        return self.properties.get(FILTER_RUN_DAYS)

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Return the filter cleaning interval."""
        if (interval := self.properties.get(FILTER_DAYS)) is None:
            return {}
        return {"filter_interval_days": interval}
