"""Device state: last reported shadow properties combined with commanded changes not yet reported.

Adapted from salus-it600-cloud (MIT) by Peterka35.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    FAN_MODE,
    HEATING_SETPOINT,
    SET_FAN_MODE,
    SET_HEATING_SETPOINT,
    SET_SYSTEM_MODE,
    SYSTEM_MODE,
)

# Commands are sent as "Set*" desired properties, devices report the result under these property names
DESIRED_TO_REPORTED = {
    SET_HEATING_SETPOINT: HEATING_SETPOINT,
    SET_SYSTEM_MODE: SYSTEM_MODE,
    SET_FAN_MODE: FAN_MODE,
}


def extract_reported(document: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return device index and reported properties from a shadow document or shadow update."""
    reported = document.get("state", {}).get("reported") or {}
    for index, value in reported.items():
        if isinstance(value, dict) and isinstance(value.get("properties"), dict):
            return index, value["properties"]
    return None


@dataclass
class _DeviceState:
    index: str | None = None
    reported: dict[str, Any] = field(default_factory=dict)
    reported_at: float | None = None
    # Reported property name -> (commanded value, time until which it overrides reports)
    pending: dict[str, tuple[Any, float]] = field(default_factory=dict)


class DeviceStateStore:
    """Device states keyed by thing name."""

    def __init__(self, pending_timeout: float, max_age: float) -> None:
        """Initialize the store.

        pending_timeout: seconds a commanded value overrides reports until the device confirms it
        max_age: seconds since the last report after which device data is no longer fresh
        """
        self._pending_timeout = pending_timeout
        self._max_age = max_age
        self._devices: dict[str, _DeviceState] = {}

    def update_reported(self, thing: str, index: str, properties: dict[str, Any], now: float) -> None:
        """Merge properties reported by the device."""
        device = self._devices.setdefault(thing, _DeviceState())
        device.index = index
        device.reported.update(properties)
        device.reported_at = now
        for name, (value, _) in list(device.pending.items()):
            if device.reported.get(name) == value:
                del device.pending[name]

    def set_pending(self, thing: str, desired: dict[str, Any], now: float) -> None:
        """Remember commanded desired properties until the device reports them."""
        device = self._devices.setdefault(thing, _DeviceState())
        for name, value in desired.items():
            if name in DESIRED_TO_REPORTED:
                device.pending[DESIRED_TO_REPORTED[name]] = (value, now + self._pending_timeout)

    def properties(self, thing: str, now: float) -> dict[str, Any]:
        """Return reported properties overridden by commanded changes the device has not reported yet."""
        device = self._devices.get(thing)
        if device is None:
            return {}
        device.pending = {name: entry for name, entry in device.pending.items() if entry[1] >= now}
        return {**device.reported, **{name: value for name, (value, _) in device.pending.items()}}

    def index(self, thing: str) -> str | None:
        """Return shadow device index of the thing."""
        device = self._devices.get(thing)
        return device.index if device else None

    def is_fresh(self, thing: str, now: float) -> bool:
        """Return whether the device reported its state recently enough."""
        device = self._devices.get(thing)
        return device is not None and device.reported_at is not None and now - device.reported_at <= self._max_age
