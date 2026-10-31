"""Real HA registry merging, tool dispatch and lifecycle regression tests."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import Context
from homeassistant.helpers import llm

from custom_components.planelocket_ai.client import PlaneLocketError, bounded_result
from custom_components.planelocket_ai.const import DOMAIN


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
    assert len(instance.tools) == 2
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

    # Check the native Ollama adapter can format the connector's actual schema.
    from homeassistant.components.ollama.entity import _format_tool

    spec = _format_tool(api.tools[0], api.custom_serializer)
    assert spec["function"]["parameters"]["properties"]["question"]["type"] == "string"
    ask.assert_awaited_once_with(
        "What movies starring Harrison Ford do we have?", intent="investigate"
    )


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


async def test_movie_acquisition_tool_supports_followup(hass, entry, context, evidence):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    tool = next(tool for tool in api.tools if tool.name.endswith("acquire_movie"))
    assert tool.annotations.read_only is False
    assert tool.annotations.idempotent is False
    from homeassistant.components.ollama.entity import _format_tool

    spec = _format_tool(tool, api.custom_serializer)
    assert {"question", "title", "year", "continuation_id"} == set(
        spec["function"]["parameters"]["properties"]
    )
    identifier = "b028ae3e-946e-4c3c-aa72-65f1056b7b15"
    evidence["continuation_id"] = identifier
    with patch.object(entry.runtime_data, "async_ask", new_callable=AsyncMock) as ask:
        ask.return_value = bounded_result(evidence, "test-only-credential")
        first = await api.async_call_tool(
            llm.ToolInput(
                tool_name=tool.name,
                tool_args={"question": "Get Example Film", "title": "Example Film"},
            )
        )
        assert first.data["continuation_id"] == identifier
        followup = await api.async_call_tool(
            llm.ToolInput(
                tool_name=tool.name,
                tool_args={
                    "question": "2026",
                    "year": 2026,
                    "continuation_id": first.data["continuation_id"],
                },
            )
        )
        assert not followup.error
        ask.assert_awaited_with("2026", intent="acquire", year=2026, continuation_id=identifier)


@pytest.mark.parametrize(
    "fields",
    [
        {"question": "get it"},
        {"question": "get it", "title": "Example", "year": True},
        {"question": "get it", "continuation_id": "invented"},
        {"question": "get it", "title": "Example", "url": "https://other.test"},
    ],
)
async def test_invalid_acquisition_does_not_call_backend(hass, entry, context, fields):
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    tool = next(tool for tool in api.tools if tool.name.endswith("acquire_movie"))
    with patch.object(entry.runtime_data, "async_ask") as ask:
        result = await api.async_call_tool(llm.ToolInput(tool_name=tool.name, tool_args=fields))
    assert result.error
    ask.assert_not_called()


async def test_acquisition_schema_requires_title_and_reports_missing_title(hass, entry, context):
    """Reproduce the live HAL question-only acquisition call before retrying."""
    api_id = await setup_entry(hass, entry)
    api = await llm.async_get_api(hass, api_id, context)
    tool = next(tool for tool in api.tools if tool.name.endswith("acquire_movie"))
    from homeassistant.components.ollama.entity import _format_tool

    spec = _format_tool(tool, api.custom_serializer)
    assert {"question", "title"} == set(spec["function"]["parameters"]["required"])
    with patch.object(entry.runtime_data, "async_ask", new_callable=AsyncMock) as ask:
        failure = await api.async_call_tool(
            llm.ToolInput(
                tool_name=tool.name, tool_args={"question": "Please acquire the movie Example Film"}
            )
        )
        assert failure.error
        assert failure.data["code"] == "missing_title"
        assert "title as separate fields" in failure.data["error"]
        ask.assert_not_called()
        ask.return_value = {"completed": True, "answer": "No request was submitted."}
        result = await api.async_call_tool(
            llm.ToolInput(
                tool_name=tool.name,
                tool_args={
                    "question": "Please acquire the movie Example Film",
                    "title": "Example Film",
                },
            )
        )
        assert not result.error
        ask.assert_awaited_once_with(
            "Please acquire the movie Example Film", intent="acquire", title="Example Film"
        )
