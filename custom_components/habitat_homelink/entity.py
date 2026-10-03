"""Base entity for Habitat HomeLink devices."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HabitatCoordinator, HabitatDevice


class HabitatEntity(CoordinatorEntity[HabitatCoordinator]):
    """Entity of a Habitat device backed by coordinator data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HabitatCoordinator, device: HabitatDevice, key: str | None = None) -> None:
        """Initialize the entity; key distinguishes multiple entities of one device."""
        super().__init__(coordinator)
        self._thing = device.thing.name
        self._attr_unique_id = f"{self._thing}_{key}" if key else self._thing
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._thing)},
            name="Habitat PTAC",
            manufacturer="Habitat / Ice Air",
            model=device.thing.model,
            via_device=(DOMAIN, device.thing.gateway),
        )

    @property
    def device(self) -> HabitatDevice | None:
        """Return current data of the device."""
        return self.coordinator.get_device(self._thing)

    @property
    def properties(self) -> dict[str, Any]:
        """Return current shadow properties of the device."""
        device = self.device
        return device.properties if device else {}

    @property
    def available(self) -> bool:
        """Return whether recent state data of the device is known."""
        device = self.device
        return super().available and device is not None and device.fresh
