"""Regressions from live household conversations; provider I/O stays mocked."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations.calibre_web import CalibreWebClient
from planelocket_agent.interaction import capabilities, classify_action
from planelocket_agent.tools.dispatcher import ToolDispatcher


def test_book_words_match_across_fields_without_relying_on_remote_phrase_search():
    client = CalibreWebClient("http://example.test", "user", "password")
    records = [
        {
            "id": 520,
            "title": "The Alloy of Law",
            "authors": ["Brandon Sanderson"],
            "formats": ["EPUB"],
            "series": None,
        },
        {
            "id": 521,
            "title": "The Alloy of Law",
            "authors": ["Another Author"],
            "formats": ["PDF"],
            "series": None,
        },
        {
            "id": 522,
            "title": "Enchanter’s End Game",
            "authors": ["David Eddings"],
            "formats": ["EPUB"],
            "series": None,
        },
    ]
    with patch.object(
        client,
        "_library_pages",
        return_value={"items": records, "total": 3, "complete": True},
    ) as pages:
        for query in (
            "The Alloy of Law by Brandon Sanderson",
            "The Alloy of Law Brandon Sanderson",
            "Brandon Sanderson",
            "Sanderson, Brandon",
        ):
            result = client.search_catalog(query)
            assert [row["id"] for row in result["items"]] == [520]
            assert result["complete"]
        assert client.search_catalog("Enchanter's End Game")["items"][0]["id"] == 522
        assert (
            client.search_catalog("The Alloy of Law by Another Author")["items"][0][
                "id"
            ]
            == 521
        )
        assert client.search_catalog("Unknown Book")["total"] == 0
        assert all(call.args == (None,) for call in pages.call_args_list)


def test_partial_book_scan_never_establishes_absence():
    client = CalibreWebClient("http://example.test", "user", "password")
    with patch.object(
        client,
        "_library_pages",
        return_value={"items": [], "total": 1000, "complete": False},
    ):
        assert client.search_catalog("The Alloy of Law")["complete"] is False


def test_backend_advertises_registered_inventory_books_and_other_reads():
    catalog = capabilities()
    description = catalog["lookup_description"].lower()
    for word in ("books", "parts", "quantities", "locations", "music", "linux"):
        assert word in description
    dispatcher = ToolDispatcher(Mock())
    assert {
        "search_books",
        "search_inventory_parts",
        "get_inventory_stock",
        "get_seasons",
        "get_episodes",
    } <= set(dispatcher.available_tools())
    assert "acquisition" in catalog["instructions"]


@pytest.mark.parametrize(
    "path,fields",
    [
        (
            "/investigate",
            {
                "intent": "acquire",
                "media_type": "tv",
                "title": "Foundation",
                "year": 2021,
                "seasons": [1],
            },
        ),
        ("/investigate", {"intent": "acquire", "title": "Dune"}),
        ("/books/acquire", {"title": "The Alloy of Law"}),
    ],
)
def test_informational_user_turn_cannot_be_authorized_by_tool_choice(
    monkeypatch, path, fields
):
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    history = [
        {"role": "user", "content": "Do we have Foundation?"},
        {
            "role": "assistant",
            "content": "Would you like to see which seasons you have?",
        },
    ]
    with (
        patch.object(api, "classify_action", return_value="lookup") as classify,
        patch.object(
            api.PlaneLocketAgent,
            "investigate",
            return_value=SimpleNamespace(
                answer="Owned season 1.", tool_calls=1, observations=(), completed=True
            ),
        ) as lookup,
        patch.object(api, "prepare_tv_request") as tv,
        patch.object(api, "prepare_movie_request") as movie,
        patch.object(api, "acquire_book") as book,
        TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client,
    ):
        result = client.post(
            path,
            json={
                "question": "Get all seasons",
                "user_question": "yes",
                "conversation_history": history,
                **fields,
            },
        ).json()
    assert result["answer"] == "Owned season 1."
    assert result["control"]["next_action"] == "respond"
    classify.assert_called_once_with("yes", history)
    assert lookup.call_args.args[0] == "yes"
    assert lookup.call_args.kwargs["conversation_history"] == history
    tv.assert_not_called()
    movie.assert_not_called()
    book.assert_not_called()


@pytest.mark.parametrize(
    "classification", ["unclear", ValueError("bad model response")]
)
def test_unresolved_intent_attempts_no_write_or_extra_confirmation(
    monkeypatch, classification
):
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    with (
        patch.object(api, "classify_action") as classify,
        patch.object(api, "acquire_book") as write,
    ):
        if isinstance(classification, Exception):
            classify.side_effect = classification
        else:
            classify.return_value = classification
        with TestClient(
            api.app, headers={"Authorization": "Bearer test-token"}
        ) as client:
            result = client.post(
                "/books/acquire",
                json={
                    "question": "Get Example",
                    "title": "Example",
                    "user_question": "yes",
                },
            ).json()
    assert result["control"]["next_action"] == "stop"
    assert "?" not in result["answer"]
    write.assert_not_called()


def test_explicit_acquisition_proceeds_once_without_new_permission(monkeypatch):
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    with (
        patch.object(api, "classify_action", return_value="acquire"),
        patch.object(
            api, "acquire_book", return_value={"answer": "Accepted search"}
        ) as write,
    ):
        with TestClient(
            api.app, headers={"Authorization": "Bearer test-token"}
        ) as client:
            result = client.post(
                "/books/acquire",
                json={
                    "question": "Get Example",
                    "title": "Example",
                    "user_question": "Get Example by Someone",
                },
            ).json()
    write.assert_called_once()
    assert result["answer"] == "Accepted search"


def test_intent_resolver_uses_original_text_and_conversation_semantically():
    with patch("planelocket_agent.interaction.OllamaClient") as client:
        client.return_value.chat.return_value = '{"action":"lookup"}'
        assert (
            classify_action("yes", [{"role": "assistant", "content": "Show seasons?"}])
            == "lookup"
        )
        messages = client.return_value.chat.call_args.args[0]
        assert '"current_user": "yes"' in messages[1]["content"]
        assert "Agreement to" in messages[0]["content"]
        client.return_value.chat.return_value = '{"action":"invented"}'
        with pytest.raises(ValueError):
            classify_action("yes", [])


def test_capability_route_requires_auth_and_reports_supported_reads(monkeypatch):
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    with TestClient(api.app) as client:
        assert client.get("/capabilities").status_code in {401, 403}
        response = client.get(
            "/capabilities", headers={"Authorization": "Bearer test-token"}
        )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert "quantities" in response.json()["lookup_description"]
