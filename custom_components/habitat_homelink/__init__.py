"""The Habitat HomeLink integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HabitatApi, HabitatAuthenticationError, HabitatConnectionError
from .const import DOMAIN
from .coordinator import HabitatCoordinator

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR]

type HabitatConfigEntry = ConfigEntry[HabitatCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HabitatConfigEntry) -> bool:
    """Set up Habitat HomeLink from a config entry."""
    api = HabitatApi(entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD], session=async_get_clientsession(hass))
    try:
        await api.authenticate()
    except HabitatAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except HabitatConnectionError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = HabitatCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    # Gateways are registered first so devices can refer to them
    device_registry = dr.async_get(hass)
    for gateway in coordinator.gateways:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, gateway)},
            manufacturer="Habitat / Ice Air",
            model="HomeLink gateway",
            name="Habitat HomeLink",
            serial_number=gateway.split("-", 1)[-1],
        )

    await coordinator.async_start_connection()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HabitatConfigEntry) -> bool:
    """Unload a config entry (the coordinator stops its MQTT connection when the entry unloads)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
