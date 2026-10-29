"""Expose PlaneLocket AI through Home Assistant's supported LLM API registry."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import PlaneLocketClient
from .const import API_NAME, CONF_TOKEN, DOMAIN
from .llm_api import PlaneLocketAPI

type PlaneLocketConfigEntry = ConfigEntry[PlaneLocketClient]


async def async_setup_entry(hass: HomeAssistant, entry: PlaneLocketConfigEntry) -> bool:
    """Register without remote I/O, so backend outages never block API merging."""
    entry.runtime_data = PlaneLocketClient(
        async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN]
    )
    entry.async_on_unload(
        llm.async_register_api(
            hass,
            PlaneLocketAPI(
                hass=hass,
                id=f"{DOMAIN}-{entry.entry_id}",
                name=API_NAME,
                entry=entry,
            ),
        )
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PlaneLocketConfigEntry) -> bool:
    """HA invokes the registered cleanup callbacks after a successful unload."""
    return True
