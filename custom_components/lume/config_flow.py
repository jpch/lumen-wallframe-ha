# -*- coding: utf-8 -*-
import voluptuous as vol
from homeassistant import config_entries

from .const import DOMAIN


class LumeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            user_input["interval_s"] = int(user_input.get("interval_s") or 60)
            user_input["client_secret"] = user_input.get("client_secret") or ""
            user_input["temp_entity"] = (user_input.get("temp_entity") or "").strip()
            return self.async_create_entry(title="Lumen-wallframe", data=user_input)
        schema = vol.Schema(
            {
                vol.Required("client_id"): str,
                vol.Optional("client_secret", default=""): str,
                vol.Optional("interval_s", default=60): vol.All(vol.Coerce(int), vol.Range(min=10, max=86400)),
                vol.Optional("temp_entity", default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
