from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import DEFAULT_API_HOST, DEFAULT_API_PORT, DOMAIN, HunonicAPIClient

CONF_API_HOST = "api_host"
CONF_API_PORT = "api_port"


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 3

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            client = HunonicAPIClient(
                self.hass,
                async_get_clientsession(self.hass),
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input.get(CONF_API_HOST, DEFAULT_API_HOST),
                user_input.get(CONF_API_PORT, DEFAULT_API_PORT),
            )
            try:
                if not await client.authenticate():
                    errors["base"] = "invalid_auth"
                elif not await client.get_devices():
                    errors["base"] = "no_devices"
                else:
                    return self.async_create_entry(title="ROL-ROI Steel Door", data=user_input)
            except Exception:
                errors["base"] = "cannot_connect"
        schema = vol.Schema({
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Optional(CONF_API_HOST, default=DEFAULT_API_HOST): str,
            vol.Optional(CONF_API_PORT, default=DEFAULT_API_PORT): vol.Coerce(int),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
