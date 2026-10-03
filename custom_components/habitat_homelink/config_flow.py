"""Config flow for Habitat HomeLink.

Adapted from salus-it600-cloud (MIT) by Peterka35.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HabitatApi, HabitatAuthenticationError, HabitatConnectionError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})
STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class HabitatConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Habitat HomeLink."""

    VERSION = 1

    async def _async_validate(self, email: str, password: str) -> str | None:
        """Log in and look for gateways; return error key or None."""
        api = HabitatApi(email, password, session=async_get_clientsession(self.hass))
        try:
            await api.authenticate()
            gateways = await api.get_gateways()
        except HabitatAuthenticationError:
            return "invalid_auth"
        except HabitatConnectionError:
            return "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error while validating Habitat login")
            return "unknown"
        finally:
            await api.close()
        return None if gateways else "no_devices"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()
            if (error := await self._async_validate(email, user_input[CONF_PASSWORD])) is None:
                return self.async_create_entry(
                    title=f"Habitat ({email})",
                    data={CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )
            errors["base"] = error
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the current password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            if (error := await self._async_validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])) is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )
