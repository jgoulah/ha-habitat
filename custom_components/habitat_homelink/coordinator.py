"""Data coordinator for Habitat HomeLink: discovery, device states and commands.

Structure adapted from salus-it600-cloud (MIT) by Peterka35.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HabitatApi, HabitatAuthenticationError, HabitatConnectionError, HabitatThing
from .const import (
    CONFIRM_REFRESH_DELAY_SECONDS,
    DOMAIN,
    METADATA_REFRESH_SECONDS,
    MODEL_PTAC_THERMOSTAT,
    PENDING_TIMEOUT_SECONDS,
    PUSH_SCAN_INTERVAL_SECONDS,
    REFRESH_ON_CONNECT,
    SCAN_INTERVAL_SECONDS,
    SET_REFRESH,
    STALE_AFTER_SECONDS,
)
from .mqtt import HabitatMqttConnection
from .state import DeviceStateStore, extract_reported

_LOGGER = logging.getLogger(__name__)


@dataclass
class HabitatDevice:
    """Current data of a device thing."""

    thing: HabitatThing
    properties: dict[str, Any] = field(default_factory=dict)
    index: str | None = None
    fresh: bool = False


class HabitatCoordinator(DataUpdateCoordinator[dict[str, HabitatDevice]]):
    """Keeps Habitat device data up to date and sends commands to devices."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: HabitatApi,
        *,
        connection_factory: Callable[..., HabitatMqttConnection] = HabitatMqttConnection,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.api = api
        self._connection_factory = connection_factory
        self._clock = clock
        self._store = DeviceStateStore(pending_timeout=PENDING_TIMEOUT_SECONDS, max_age=STALE_AFTER_SECONDS)
        self._things: list[HabitatThing] | None = None
        self._things_fetched_at = 0.0
        self._connection: HabitatMqttConnection | None = None
        self._cancel_confirmation: CALLBACK_TYPE | None = None
        self.push_available = False

    @property
    def gateways(self) -> list[str]:
        """Return gateway thing names of the account."""
        return sorted({thing.gateway for thing in self._things or []})

    def _device_things(self) -> list[HabitatThing]:
        """Return things that get entities (PTAC thermostats)."""
        return [thing for thing in self._things or [] if thing.model == MODEL_PTAC_THERMOSTAT]

    def get_device(self, thing: str) -> HabitatDevice | None:
        """Return current data of a device."""
        return (self.data or {}).get(thing)

    async def _async_update_data(self) -> dict[str, HabitatDevice]:
        now = self._clock()
        try:
            if self._things is None or now - self._things_fetched_at >= METADATA_REFRESH_SECONDS:
                await self._async_discover(now)
            results = await asyncio.gather(
                *(self.api.get_shadow(thing.name) for thing in self._device_things()), return_exceptions=True
            )
        except HabitatAuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err

        errors = []
        for thing, result in zip(self._device_things(), results, strict=True):
            if isinstance(result, HabitatAuthenticationError):
                raise ConfigEntryAuthFailed(str(result)) from result
            if isinstance(result, BaseException):
                errors.append(result)
            elif (reported := extract_reported(result)) is not None:
                self._store.update_reported(thing.name, reported[0], reported[1], now)
        if errors:
            if not any(self._store.is_fresh(thing.name, now) for thing in self._device_things()):
                raise UpdateFailed(f"Error communicating with Habitat cloud: {errors[0]}")
            _LOGGER.warning("Failed to refresh device states, keeping last known states: %s", errors[0])
        return self._build_data(now)

    async def _async_discover(self, now: float) -> None:
        try:
            things = await self.api.discover()
        except HabitatConnectionError as err:
            if self._things is None:
                raise UpdateFailed(f"Error communicating with Habitat cloud: {err}") from err
            _LOGGER.warning("Failed to refresh device list, using the previous one: %s", err)
            return
        self._things = things
        self._things_fetched_at = now
        if self._connection is not None:
            self._connection.set_things([thing.name for thing in self._device_things()])

    def _build_data(self, now: float) -> dict[str, HabitatDevice]:
        return {
            thing.name: HabitatDevice(
                thing=thing,
                properties=self._store.properties(thing.name, now),
                index=self._store.index(thing.name),
                fresh=self._store.is_fresh(thing.name, now),
            )
            for thing in self._device_things()
        }

    async def async_start_connection(self) -> None:
        """Connect to AWS IoT for commands and pushed device state changes."""
        if not self.gateways:
            return
        self._connection = self._connection_factory(
            credentials_provider=self.api.get_aws_credentials,
            client_id_prefix=self.gateways[0],
            on_shadow_document=self._handle_shadow_document,
            on_push_available=self._handle_push_available,
            on_connected=self._handle_connected,
        )
        await self._connection.async_start([thing.name for thing in self._device_things()])

    async def async_shutdown(self) -> None:
        """Stop polling and the AWS IoT connection."""
        await super().async_shutdown()
        if self._cancel_confirmation is not None:
            self._cancel_confirmation()
            self._cancel_confirmation = None
        if self._connection is not None:
            await self._connection.async_stop()

    @callback
    def _handle_shadow_document(self, thing: str, document: dict[str, Any]) -> None:
        if (reported := extract_reported(document)) is None:
            return
        if thing not in {device.name for device in self._device_things()}:
            return
        now = self._clock()
        self._store.update_reported(thing, reported[0], reported[1], now)
        self.async_set_updated_data(self._build_data(now))

    @callback
    def _handle_push_available(self, available: bool) -> None:
        self.push_available = available
        self.update_interval = timedelta(seconds=PUSH_SCAN_INTERVAL_SECONDS if available else SCAN_INTERVAL_SECONDS)

    @callback
    def _handle_connected(self) -> None:
        """Ask thermostats to report their full state, as the app does after connecting."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_request_device_refresh(), "habitat_homelink_refresh"
        )

    async def _async_request_device_refresh(self) -> None:
        for device in (self.data or {}).values():
            if device.index is None:
                continue
            try:
                await self._connection.async_publish_shadow(
                    device.thing.name, device.index, {SET_REFRESH: REFRESH_ON_CONNECT}
                )
            except HabitatConnectionError as err:
                _LOGGER.debug("Refresh request to %s failed: %s", device.thing.name, err)

    async def async_send(self, thing: str, properties: dict[str, Any]) -> None:
        """Set desired properties of a device and show them until the device reports them."""
        device = self.get_device(thing)
        if device is None or device.index is None:
            raise HomeAssistantError(f"Habitat device {thing} is not ready")
        if self._connection is None:
            raise HomeAssistantError("Not connected to Habitat cloud")
        try:
            await self._connection.async_publish_shadow(thing, device.index, properties)
        except HabitatConnectionError as err:
            raise HomeAssistantError(f"Habitat device did not accept the command: {err}") from err
        now = self._clock()
        self._store.set_pending(thing, properties, now)
        self.async_set_updated_data(self._build_data(now))
        if not self.push_available:
            self._schedule_confirmation_refresh()

    @callback
    def _schedule_confirmation_refresh(self) -> None:
        if self._cancel_confirmation is not None:
            self._cancel_confirmation()
        self._cancel_confirmation = async_call_later(
            self.hass, CONFIRM_REFRESH_DELAY_SECONDS, self._async_confirmation_refresh
        )

    async def _async_confirmation_refresh(self, _now: datetime) -> None:
        self._cancel_confirmation = None
        await self.async_request_refresh()
