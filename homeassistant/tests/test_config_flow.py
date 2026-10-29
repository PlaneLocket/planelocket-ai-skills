"""HA's real config-flow manager with only the HTTP health call mocked."""

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.planelocket_ai.client import PlaneLocketError
from custom_components.planelocket_ai.const import DOMAIN
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

INPUT = {"url": "https://ai.example.test/", "token": "test-only-credential"}
HEALTH = "custom_components.planelocket_ai.client.PlaneLocketClient.async_health"


async def test_create(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    with patch(HEALTH, new_callable=AsyncMock) as health:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {**INPUT, "url": "https://ai.example.test"}
    health.assert_awaited_once()
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "code", ["cannot_connect", "timeout", "invalid_response", "service_unavailable"]
)
async def test_health_error(hass, code):
    with patch(HEALTH, side_effect=PlaneLocketError(code)):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=INPUT
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": code}
    assert INPUT["token"] not in str(result)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("url", "http://ai.example.test", "invalid_url"),
        ("token", "bad\r\ntoken", "invalid_token"),
    ],
)
async def test_invalid_input_no_network(hass, field, value, code):
    with patch(HEALTH) as health:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data={**INPUT, field: value}
        )
    assert result["errors"] == {"base": code}
    health.assert_not_called()


async def test_single_instance(hass, entry):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.mark.parametrize(
    ("source", "step", "reason"),
    [
        (config_entries.SOURCE_RECONFIGURE, "reconfigure", "reconfigure_successful"),
        (config_entries.SOURCE_REAUTH, "reauth_confirm", "reauth_successful"),
    ],
)
async def test_replace_credentials(hass, entry, source, step, reason):
    entry.add_to_hass(hass)
    original_id = entry.entry_id
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        data=entry.data if source == config_entries.SOURCE_REAUTH else None,
    )
    assert result["step_id"] == step
    assert INPUT["token"] not in str(result)
    replacement = {"url": "https://replacement.example.test", "token": "replacement-test-only"}
    with patch(HEALTH, new_callable=AsyncMock):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], replacement)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert entry.entry_id == original_id
    assert entry.data == replacement
    await hass.async_block_till_done()
