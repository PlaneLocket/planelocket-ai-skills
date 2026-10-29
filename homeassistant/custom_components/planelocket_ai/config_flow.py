"""Configure the endpoint and private bearer token without running inference."""

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .client import PlaneLocketClient, PlaneLocketError, normalize_token, normalize_url
from .const import API_NAME, CONF_TOKEN, DEFAULT_URL, DOMAIN


def _schema(url: str = DEFAULT_URL) -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Required(CONF_URL, default=url): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            probatio.Required(CONF_TOKEN): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
        }
    )


class PlaneLocketConfigFlow(ConfigFlow, domain=DOMAIN):
    """One connector instance; reconfigure to change its endpoint or token."""

    VERSION = 1

    async def _validate(self, user_input: Mapping[str, Any]) -> dict[str, str]:
        data = {
            CONF_URL: normalize_url(user_input[CONF_URL]),
            CONF_TOKEN: normalize_token(user_input[CONF_TOKEN]),
        }
        client = PlaneLocketClient(
            async_get_clientsession(self.hass), data[CONF_URL], data[CONF_TOKEN]
        )
        await client.async_health()
        return data

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate connection, explicitly not authentication, at setup."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            try:
                data = await self._validate(user_input)
            except PlaneLocketError as err:
                errors["base"] = err.code
            else:
                return self.async_create_entry(title=API_NAME, data=data)
        # Do not echo submitted credentials into suggested values or placeholders.
        return self.async_show_form(step_id="user", data_schema=_schema(), errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the token or endpoint without changing the registered API ID."""
        entry = self._get_reconfigure_entry()
        return await self._async_replace("reconfigure", entry, user_input)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start credential replacement after a rejected lookup."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept a replacement credential; authenticate on the next real lookup."""
        entry = self._get_reauth_entry()
        return await self._async_replace("reauth_confirm", entry, user_input)

    async def _async_replace(
        self, step_id: str, entry: Any, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors = {}
        if user_input is not None:
            try:
                data = await self._validate(user_input)
            except PlaneLocketError as err:
                errors["base"] = err.code
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id=step_id, data_schema=_schema(entry.data[CONF_URL]), errors=errors
        )
