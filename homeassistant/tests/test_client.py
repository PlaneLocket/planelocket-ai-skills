"""Real aiohttp transport on loopback; production endpoints always require HTTPS."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.planelocket_ai import client as client_module
from custom_components.planelocket_ai.client import (
    PlaneLocketClient,
    PlaneLocketError,
    bounded_result,
    normalize_token,
    normalize_url,
)
from custom_components.planelocket_ai.const import MAX_RESPONSE_BYTES, MAX_TOOL_RESULT_BYTES

BASE = "https://ai.example.test"
TOKEN = "test-only-credential"
pytestmark = pytest.mark.usefixtures("socket_enabled")


async def test_capability_metadata_uses_authenticated_bounded_get(transport):
    transport.respond(
        {"version": 1, "lookup_description": "Test records", "instructions": "Test instructions"}
    )
    # The global metadata fixture isolates registration; this test exercises real transport.
    from unittest.mock import patch

    from custom_components.planelocket_ai.client import PlaneLocketClient

    with patch.object(PlaneLocketClient, "async_capabilities", new=ORIGINAL_CAPABILITIES):
        result = await transport.client.async_capabilities()
    assert result["lookup_description"] == "Test records"
    method, url, kwargs = transport.calls[0]
    assert method == "GET" and url == BASE + "/capabilities"
    assert kwargs["headers"]["Authorization"] == "Bearer " + TOKEN
    assert kwargs["timeout"].total == 2


ORIGINAL_CAPABILITIES = PlaneLocketClient.async_capabilities


@pytest.fixture
async def transport(aiohttp_server):
    """Map the HTTPS test origin to a real local server; record transport options."""
    state = SimpleNamespace(calls=[], response=None, exception=None)

    async def handle(request):
        return await state.response(request)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handle)
    server = await aiohttp_server(app)
    async with aiohttp.ClientSession() as session:

        def request(method, url, **kwargs):
            assert url.startswith(BASE + "/")
            state.calls.append((method, url, kwargs))
            if state.exception is not None:
                raise state.exception
            return session.request(method, server.make_url(url.removeprefix(BASE)), **kwargs)

        state.session = SimpleNamespace(request=request)
        state.client = PlaneLocketClient(state.session, BASE, TOKEN)

        def respond(
            payload=None, *, status=200, body=None, headers=None, content_type="application/json"
        ):
            async def response(request):
                return web.Response(
                    status=status,
                    body=body if body is not None else json.dumps(payload).encode(),
                    content_type=content_type,
                    headers=headers,
                )

            state.response = response

        state.respond = respond
        yield state


@pytest.mark.parametrize(
    "value",
    [
        "http://ai.example.test",
        "https://u:p@ai.example.test",
        "https://ai.example.test/api",
        "https://ai.example.test?token=secret",
        "https://ai.example.test#fragment",
        "",
        None,
    ],
)
def test_reject_unsafe_url(value):
    with pytest.raises(PlaneLocketError, match="^invalid_url$"):
        normalize_url(value)


def test_normalize_origin():
    assert normalize_url(" https://AI.example.test/ ") == BASE


@pytest.mark.parametrize("value", ["", "\n", "bad\r\ntoken", "contains space", "é", None])
def test_reject_invalid_token(value):
    with pytest.raises(PlaneLocketError, match="^invalid_token$"):
        normalize_token(value)


async def test_authenticated_question_and_evidence(transport, evidence):
    transport.respond(evidence)
    result = await transport.client.async_ask("What movies starring Harrison Ford do we have?")
    assert result["observations"] == evidence["observations"]
    assert result["completed"] is True
    assert result["observations_omitted"] == 0
    method, url, kwargs = transport.calls[0]
    assert (method, url) == ("POST", BASE + "/investigate")
    assert kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert kwargs["json"] == {"question": "What movies starring Harrison Ford do we have?"}
    assert kwargs["allow_redirects"] is False
    assert "ssl" not in kwargs  # Shared session's normal certificate verification.
    assert kwargs["timeout"].total == 120


async def test_health_sends_no_credential(transport):
    transport.respond({"status": "ok"})
    await transport.client.async_health()
    assert "Authorization" not in transport.calls[0][2]["headers"]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "invalid_auth"),
        (403, "invalid_auth"),
        (429, "service_unavailable"),
        (500, "service_unavailable"),
        (302, "service_unavailable"),
    ],
)
async def test_status_errors_are_sanitized_without_retries(transport, status, code):
    transport.respond(status=status, body=TOKEN.encode())
    with pytest.raises(PlaneLocketError, match=f"^{code}$") as error:
        await transport.client.async_ask("our movies?")
    assert TOKEN not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (TimeoutError("secret detail"), "timeout"),
        (aiohttp.ClientConnectionError("secret detail"), "cannot_connect"),
    ],
)
async def test_transport_errors(transport, exception, code):
    transport.exception = exception
    with pytest.raises(PlaneLocketError, match=f"^{code}$"):
        await transport.client.async_ask("our movies?")


@pytest.mark.parametrize("question", ["", "   ", "q" * 2001, None, 42])
async def test_invalid_question_never_sends(transport, question):
    with pytest.raises(PlaneLocketError, match="^invalid_question$"):
        await transport.client.async_ask(question)
    assert not transport.calls


@pytest.mark.parametrize(
    "body",
    ["{", "[]", "null", '{"status":"ok"}', "[" * 1200],
    ids=["syntax", "array", "null", "schema", "deep"],
)
async def test_invalid_remote_json(transport, body):
    transport.respond(body=body.encode())
    with pytest.raises(PlaneLocketError, match="^invalid_response$"):
        await transport.client.async_ask("our movies?")


async def test_reject_html(transport):
    transport.respond(body=b"<html>login</html>", content_type="text/html")
    with pytest.raises(PlaneLocketError, match="^invalid_response$"):
        await transport.client.async_health()


async def test_reject_content_length(transport):
    transport.respond(body=b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(PlaneLocketError, match="^response_too_large$"):
        await transport.client.async_health()


async def test_chunked_response_cap(transport):
    async def oversized(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        await response.write(b"x" * (MAX_RESPONSE_BYTES + 1))
        await response.write_eof()
        return response

    transport.response = oversized
    with pytest.raises(PlaneLocketError, match="^response_too_large$"):
        await transport.client.async_health()


async def test_timeout_includes_body_consumption(transport):
    async def slow_body(request):
        response = web.StreamResponse(headers={"Content-Type": "application/json"})
        await response.prepare(request)
        await asyncio.sleep(0.1)
        return response

    transport.response = slow_body
    with patch.object(client_module, "HEALTH_TIMEOUT", 0.01):
        with pytest.raises(PlaneLocketError, match="^timeout$"):
            await transport.client.async_health()


async def test_cancellation_propagates(transport):
    transport.exception = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await transport.client.async_ask("our movies?")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer", ""),
        ("answer", 1),
        ("completed", "true"),
        ("completed", 1),
        ("tool_calls", True),
        ("tool_calls", -1),
        ("observations", {}),
        ("observations", ["invalid"]),
    ],
)
def test_validate_contract(evidence, field, value):
    evidence[field] = value
    with pytest.raises(PlaneLocketError, match="^invalid_response$"):
        bounded_result(evidence, TOKEN)


def test_bounded_unicode_result_marks_omissions(evidence):
    evidence["answer"] = "🎬" * 10000
    evidence["observations"] += [{"tool": "example", "result": "x" * 20000}]
    result = bounded_result(evidence, TOKEN)
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_TOOL_RESULT_BYTES
    assert result["answer_truncated"] is True
    assert result["observations_omitted"] > 0


def test_redact_echoed_token(evidence):
    evidence["answer"] = TOKEN
    evidence["observations"][0]["result"] = [{TOKEN: TOKEN}]
    assert TOKEN not in json.dumps(bounded_result(evidence, TOKEN))


def test_reject_nonfinite_observation(evidence):
    evidence["observations"] = [{"result": float("nan")}]
    with pytest.raises(PlaneLocketError, match="^invalid_response$"):
        bounded_result(evidence, TOKEN)


@pytest.mark.parametrize("location", ["tool_calls", "observation", "deep_observation"])
def test_reject_values_ha_cannot_serialize(evidence, location):
    if location == "tool_calls":
        evidence["tool_calls"] = 2**80
    elif location == "observation":
        evidence["observations"] = [{"value": 2**80}]
    else:
        nested = {}
        for _ in range(40):
            nested = {"nested": nested}
        evidence["observations"] = [nested]
    with pytest.raises(PlaneLocketError, match="^invalid_response$"):
        bounded_result(evidence, TOKEN)


def test_incomplete_unicode_result_is_serializable_and_bounded(evidence):
    from homeassistant.helpers.json import json_dumps

    evidence["completed"] = False
    evidence["control"].update(outcome="blocked", next_action="stop")
    evidence["answer"] = "🎬" * 10000
    result = bounded_result(evidence, TOKEN)
    assert len(json_dumps(result).encode()) <= MAX_TOOL_RESULT_BYTES
    assert "error" in result


async def test_acquisition_transport_preserves_state_when_evidence_is_omitted(transport, evidence):
    identifier = "b028ae3e-946e-4c3c-aa72-65f1056b7b15"
    evidence["continuation_id"] = identifier
    evidence["observations"] = [{"large": "x" * MAX_TOOL_RESULT_BYTES}]
    transport.respond(evidence)
    result = await transport.client.async_ask(
        "get Example Film", intent="acquire", title="Example Film"
    )
    assert result["continuation_id"] == identifier
    assert result["observations_omitted"] == 1
    assert len(json.dumps(result).encode()) <= MAX_TOOL_RESULT_BYTES
    assert transport.calls[-1][2]["json"] == {
        "question": "get Example Film",
        "intent": "acquire",
        "title": "Example Film",
    }
    await transport.client.async_ask(
        "2026", intent="acquire", continuation_id=identifier, year=2026
    )
    assert transport.calls[-1][2]["json"] == {
        "question": "2026",
        "intent": "acquire",
        "continuation_id": identifier,
        "year": 2026,
    }


@pytest.mark.parametrize("identifier", ["x" * 10000, 123, {}, "invalid"])
def test_invalid_continuation_is_not_returned(evidence, identifier):
    evidence["continuation_id"] = identifier
    with pytest.raises(PlaneLocketError, match="invalid_response"):
        bounded_result(evidence, TOKEN)


async def test_tv_acquisition_transport_keeps_scope_and_identity(transport, evidence):
    transport.respond(evidence)
    await transport.client.async_ask(
        "Get Example Series seasons 1 and 3",
        intent="acquire",
        media_type="tv",
        title="Example Series",
        year=2020,
        seasons=[3, 1],
    )
    assert transport.calls[-1][2]["json"] == {
        "question": "Get Example Series seasons 1 and 3",
        "intent": "acquire",
        "media_type": "tv",
        "title": "Example Series",
        "year": 2020,
        "seasons": [3, 1],
    }
    identifier = "b028ae3e-946e-4c3c-aa72-65f1056b7b15"
    await transport.client.async_ask(
        "all seasons",
        intent="acquire",
        media_type="tv",
        title="Example Series",
        continuation_id=identifier,
        all_seasons=True,
    )
    assert transport.calls[-1][2]["json"]["all_seasons"] is True
    assert transport.calls[-1][2]["json"]["continuation_id"] == identifier


@pytest.mark.parametrize(
    "scope",
    [
        {"seasons": [True]},
        {"seasons": ["2"]},
        {"all_seasons": 1},
    ],
)
async def test_invalid_tv_transport_never_sends(transport, scope):
    with pytest.raises(PlaneLocketError, match="invalid_question"):
        await transport.client.async_ask(
            "get it", intent="acquire", media_type="tv", title="Example Series", **scope
        )
    assert not transport.calls


async def test_book_routes_preserve_choice_and_authentication(transport, evidence):
    identifier = "b028ae3e-946e-4c3c-aa72-65f1056b7b15"
    evidence["continuation_id"] = identifier
    transport.respond(evidence)
    result = await transport.client.async_search_books("Example Author")
    assert result["completed"]
    assert transport.calls[-1][1] == BASE + "/books/search"
    assert transport.calls[-1][2]["json"] == {"query": "Example Author"}
    result = await transport.client.async_acquire_book(
        "option 1",
        "Example Book",
        author="Example Author",
        book_format="EPUB",
        continuation_id=identifier,
        choice=1,
    )
    method, url, options = transport.calls[-1]
    assert (method, url) == ("POST", BASE + "/books/acquire")
    assert options["headers"]["Authorization"] == "Bearer " + TOKEN
    assert options["json"] == {
        "question": "option 1",
        "title": "Example Book",
        "author": "Example Author",
        "format": "EPUB",
        "continuation_id": identifier,
        "choice": 1,
    }
    assert result["continuation_id"] == identifier


@pytest.mark.parametrize(
    "fields",
    [
        {"choice": True},
        {"author": " "},
        {"continuation_id": "invented"},
        {"title": None},
    ],
)
async def test_invalid_book_fields_never_send(transport, fields):
    if "format" in fields:
        fields["book_format"] = fields.pop("format")
    with pytest.raises(PlaneLocketError, match="invalid_question"):
        await transport.client.async_acquire_book("get it", **{"title": "Example Book", **fields})
    assert not transport.calls


@pytest.mark.parametrize("status", [422, 429, 503])
async def test_backend_validation_answer_is_preserved_generically(transport, evidence, status):
    evidence["answer"] = "The backend does not support that constraint."
    evidence["control"].update(outcome="blocked", next_action="stop")
    transport.respond(evidence, status=status)
    result = await transport.client.async_acquire_book(
        "Get Example", "Example", book_format="FUTURE_FORMAT"
    )
    assert result["answer"] == evidence["answer"]
    assert result["control"]["outcome"] == "blocked"
    assert transport.calls[-1][2]["json"]["format"] == "FUTURE_FORMAT"


async def test_season_policy_is_forwarded_for_backend_validation(transport, evidence):
    transport.respond(evidence)
    await transport.client.async_ask(
        "Get Example",
        intent="acquire",
        media_type="tv",
        title="Example",
        seasons=[1001, 1001],
        all_seasons=True,
    )
    assert transport.calls[-1][2]["json"]["seasons"] == [1001, 1001]
    assert transport.calls[-1][2]["json"]["all_seasons"] is True


async def test_identity_field_limits_are_owned_by_backend(transport, evidence):
    transport.respond(evidence)
    await transport.client.async_acquire_book("Get Example", "T" * 600, author="A" * 400)
    assert len(transport.calls[-1][2]["json"]["title"]) == 600
    assert len(transport.calls[-1][2]["json"]["author"]) == 400
