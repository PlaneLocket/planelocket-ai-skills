"""Real HA registry merging, tool dispatch and lifecycle regression tests."""

from unittest.mock import AsyncMock, patch

import pytest
from custom_components.planelocket_ai.client import PlaneLocketError, bounded_result
from custom_components.planelocket_ai.const import DOMAIN
from homeassistant.core import Context
from homeassistant.helpers import llm


@pytest.fixture
def context():
    return llm.LLMContext(
        platform="ollama",
        context=Context(),
        language="en",
        assistant="conversation",
        device_id=None,
    )


async def setup_entry(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return f"{DOMAIN}-{entry.entry_id}"


async def test_setup_registers_without_network_and_unload_preserves_assist(hass, entry, context):
    with patch("custom_components.planelocket_ai.client.PlaneLocketClient.async_health") as health:
        api_id = await setup_entry(hass, entry)
    health.assert_not_called()
    apis = {api.id for api in llm.async_get_apis(hass)}
    assert api_id in apis
    instance = await llm.async_get_api(hass, api_id, context)
    assert len(instance.tools) == 1
    assert instance.tools[0].integration == DOMAIN
    assert instance.tools[0].annotations.read_only is True
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert api_id not in {api.id for api in llm.async_get_apis(hass)}
    assert {api.id for api in llm.async_get_apis(hass)} == apis - {api_id}


class NativeDeviceTool(llm.Tool):
    """A sentinel proving HA's own merger preserves the existing tool path."""

    name = "HassTurnOn"
    integration = "intent"

    async def async_call(self, hass, tool_input, llm_context):
        return llm.ToolResult(data={"device_control": "retained"})


class ExistingAssistAPI(llm.API):
    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(
            api=self,
            api_prompt="Existing device instructions.",
            llm_context=llm_context,
            tools=[NativeDeviceTool()],
        )


async def test_merged_apis_keep_device_tool_callable_during_backend_outage(hass, entry, context):
    # Use the real HA API registry/merger, with a sentinel device tool (no real devices).
    unregister = llm.async_register_api(
        hass, ExistingAssistAPI(hass=hass, id="assist", name="Assist")
    )
    try:
        api_id = await setup_entry(hass, entry)
        merged = await llm.async_get_api(hass, ["assist", api_id], context)
        assert "Existing device instructions." in merged.api_prompt
        native = next(tool for tool in merged.tools if tool.name.endswith("HassTurnOn"))
        household = next(tool for tool in merged.tools if tool.name.endswith("ask_household"))
        # HA adds a namespace when APIs are merged; dispatch the actual returned name.
        with patch.object(
            entry.runtime_data, "async_ask", side_effect=PlaneLocketError("cannot_connect")
        ):
            failure = await merged.async_call_tool(
                llm.ToolInput(
                    tool_name=household.name, tool_args={"question": "What movies do we have?"}
                )
            )
            assert failure.error
            result = await merged.async_call_tool(
                llm.ToolInput(tool_name=native.name, tool_args={})
            )
            assert result.data == {"device_control": "retained"}
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert (await llm.async_get_api(hass, "assist", context)).tools[0].name == "HassTurnOn"
    finally:
        unregister()


async def test_acceptance_evidence_through_registered_api(hass, entry, context, evidence):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    with patch.object(entry.runtime_data, "async_ask", new_callable=AsyncMock) as ask:
        ask.return_value = bounded_result(evidence, "test-only-credential")
        result = await api.async_call_tool(
            llm.ToolInput(
                tool_name=api.tools[0].name,
                tool_args={"question": "What movies starring Harrison Ford do we have?"},
            )
        )
    assert not result.error
    assert result.data["observations"] == evidence["observations"]
    ask.assert_awaited_once_with("What movies starring Harrison Ford do we have?")


@pytest.mark.parametrize(
    "code",
    ["timeout", "cannot_connect", "invalid_response", "response_too_large", "service_unavailable"],
)
async def test_tool_errors_are_reported(hass, entry, context, code):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    with patch.object(entry.runtime_data, "async_ask", side_effect=PlaneLocketError(code)):
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=api.tools[0].name, tool_args={"question": "our library?"})
        )
    assert result.error
    assert result.data["code"] == code


async def test_auth_failure_starts_reauth(hass, entry, context):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    with (
        patch.object(entry.runtime_data, "async_ask", side_effect=PlaneLocketError("invalid_auth")),
        patch.object(type(entry), "async_start_reauth") as reauth,
    ):
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=api.tools[0].name, tool_args={"question": "our library?"})
        )
    assert result.error
    assert result.data["code"] == "invalid_auth"
    reauth.assert_called_once_with(hass)


async def test_incomplete_is_not_success(hass, entry, context, evidence):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    evidence["completed"] = False
    with patch.object(
        entry.runtime_data, "async_ask", return_value=bounded_result(evidence, "token")
    ):
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=api.tools[0].name, tool_args={"question": "our library?"})
        )
    assert result.error
    assert not result.data["completed"]


@pytest.mark.parametrize(
    "arguments",
    [{}, {"question": 1}, {"question": "x" * 2001}, {"question": "x", "url": "https://other.test"}],
)
async def test_invalid_tool_arguments_never_reach_backend(hass, entry, context, arguments):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    with patch.object(entry.runtime_data, "async_ask") as ask:
        result = await api.async_call_tool(
            llm.ToolInput(tool_name=api.tools[0].name, tool_args=arguments)
        )
    assert result.error
    ask.assert_not_called()
