"""Actual HA tool dispatch across turns, with all backend operations mocked."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.conversation.chat_log import UserContent, current_chat_log
from homeassistant.core import Context
from homeassistant.helpers import llm

from custom_components.planelocket_ai.client import PlaneLocketError
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


async def instance(hass, entry, context):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    return await llm.async_get_api(hass, f"{DOMAIN}-{entry.entry_id}", context)


@pytest.mark.parametrize("outcome", ["blocked", "uncertain"])
async def test_stop_fences_sequential_and_parallel_followup_calls(
    hass, entry, context, evidence, outcome
):
    api = await instance(hass, entry, context)
    evidence["control"].update(outcome=outcome, next_action="stop")
    with (
        patch.object(entry.runtime_data, "async_ask", new_callable=AsyncMock) as ask,
        patch.object(entry.runtime_data, "async_search_books", new_callable=AsyncMock) as search,
        patch.object(entry.runtime_data, "async_acquire_book", new_callable=AsyncMock) as acquire,
    ):
        ask.return_value = evidence
        first = await api.async_call_tool(
            llm.ToolInput(tool_name="ask_household", tool_args={"question": "Do I have Example?"})
        )
        followups = await asyncio.gather(
            *[
                api.async_call_tool(
                    llm.ToolInput(tool_name="search_books", tool_args={"query": "Example"})
                ),
                api.async_call_tool(
                    llm.ToolInput(
                        tool_name="acquire_book",
                        tool_args={"question": "Get Example", "title": "Example"},
                    )
                ),
            ]
        )
        assert all(result.data == first.data for result in followups)
        ask.assert_awaited_once()
        search.assert_not_awaited()
        acquire.assert_not_awaited()
        # A later user turn gets a new API instance, not a permanently blocked account.
        next_turn = await llm.async_get_api(hass, f"{DOMAIN}-{entry.entry_id}", context)
        search.return_value = {
            **evidence,
            "control": {
                "version": 1,
                "outcome": "completed",
                "next_action": "respond",
                "partial": False,
            },
        }
        result = await next_turn.async_call_tool(
            llm.ToolInput(tool_name="search_books", tool_args={"query": "Example"})
        )
        assert not result.error
        search.assert_awaited_once()


async def test_original_user_turn_and_followup_history_are_forwarded(
    hass, entry, context, evidence
):
    api = await instance(hass, entry, context)
    history = [
        UserContent(content="Do we have Foundation?"),
        SimpleNamespace(role="assistant", content="Would you like to see which seasons you have?"),
        UserContent(content="yes"),
        SimpleNamespace(role="tool_result", content="Get every season"),
    ]
    token = current_chat_log.set(SimpleNamespace(content=history))
    try:
        with patch.object(entry.runtime_data, "async_ask", new_callable=AsyncMock) as ask:
            ask.return_value = evidence
            await api.async_call_tool(
                llm.ToolInput(
                    tool_name="acquire_tv",
                    tool_args={"question": "Acquire Foundation", "title": "Foundation"},
                )
            )
        kwargs = ask.call_args.kwargs
        assert kwargs["user_question"] == "yes"
        assert kwargs["conversation_history"] == [
            {"role": "user", "content": "Do we have Foundation?"},
            {"role": "assistant", "content": "Would you like to see which seasons you have?"},
        ]
    finally:
        current_chat_log.reset(token)


async def test_new_backend_capabilities_are_discoverable_without_adapter_edits(
    hass, entry, context, capability_metadata
):
    capability_metadata.return_value = {
        "lookup_description": "New records: workshop stock, books, and future collections.",
        "instructions": "Only backend-advertised actions are supported.",
    }
    api = await instance(hass, entry, context)
    assert api.tools[0].description == capability_metadata.return_value["lookup_description"]
    assert capability_metadata.return_value["instructions"] in api.api_prompt


async def test_capability_outage_keeps_static_tools_available(
    hass, entry, context, capability_metadata
):
    capability_metadata.side_effect = PlaneLocketError("cannot_connect")
    api = await instance(hass, entry, context)
    assert len(api.tools) == 5
    assert api.tools[0].name == "ask_household"


async def test_parallel_call_queued_behind_stop_never_reaches_backend(
    hass, entry, context, evidence
):
    api = await instance(hass, entry, context)
    entered, release = asyncio.Event(), asyncio.Event()
    evidence["control"].update(outcome="uncertain", next_action="stop")

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return evidence

    with (
        patch.object(entry.runtime_data, "async_ask", side_effect=delayed) as ask,
        patch.object(entry.runtime_data, "async_search_books", new_callable=AsyncMock) as search,
    ):
        first = asyncio.create_task(
            api.async_call_tool(
                llm.ToolInput(tool_name="ask_household", tool_args={"question": "Check Example"})
            )
        )
        await entered.wait()
        second = asyncio.create_task(
            api.async_call_tool(
                llm.ToolInput(tool_name="search_books", tool_args={"query": "Example"})
            )
        )
        release.set()
        results = await asyncio.gather(first, second)
        assert results[0].data == results[1].data
        ask.assert_awaited_once()
        search.assert_not_awaited()
