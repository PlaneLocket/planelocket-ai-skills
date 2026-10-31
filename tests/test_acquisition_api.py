"""Exercise deterministic acquisition through HTTP with all external I/O mocked."""

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    storage = SeerrRequestStorage(tmp_path / "requests.sqlite3")
    storage.initialize()
    monkeypatch.setattr(api, "seerr_storage", storage)
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        yield client


@pytest.fixture
def services():
    movies = [
        {
            "title": "Example Film",
            "mediaType": "movie",
            "id": 11,
            "releaseDate": "1984-01-01",
        },
        {
            "title": "Example Film",
            "mediaType": "movie",
            "id": 22,
            "releaseDate": "2026-01-01",
        },
    ]
    with (
        patch(
            "planelocket_agent.integrations.seerr_resolver.search_media",
            return_value={"complete": True, "results": movies},
        ) as search,
        patch(
            "planelocket_agent.integrations.seerr_resolver.get_media_details",
            return_value={
                "availability": "unknown",
                "availability_4k": "unknown",
                "mediaInfo": {},
            },
        ) as details,
        patch("planelocket_agent.integrations.seerr_workflow.request_movie") as submit,
        patch.object(api.PlaneLocketAgent, "investigate") as agent,
    ):
        yield search, details, submit, agent
        submit.assert_not_called()


@pytest.mark.parametrize(
    "selection", ["2026", "the new one", "latest", "the 2026 version"]
)
def test_two_turn_movie_resolution(client, services, selection):
    search, details, submit, agent = services
    first = client.post(
        "/investigate",
        json={
            "question": "Go get Example Film.",
            "intent": "acquire",
            "title": "Example Film",
        },
    ).json()
    assert first["continuation_id"]
    assert "1984" in first["answer"] and "2026" in first["answer"]
    response = client.post(
        "/investigate",
        json={"question": selection, "continuation_id": first["continuation_id"]},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["observations"][0]["media_id"] == 22
    assert result["observations"][0]["submission"] == {
        "submitted": False,
        "reason": "dry_run",
    }
    assert "No request was submitted" in result["answer"]
    assert search.call_args.args == ("Example Film",)
    assert details.call_args.kwargs == {"media_type": "movie", "media_id": 22}
    agent.assert_not_called()
    assert (
        client.post(
            "/investigate",
            json={"question": selection, "continuation_id": first["continuation_id"]},
        ).status_code
        == 400
    )


def test_invalid_selection_preserves_continuation(client, services):
    first = client.post("/investigate", json={"question": "Get Example Film"}).json()
    for selection in ["yes", "1999"]:
        result = client.post(
            "/investigate",
            json={"question": selection, "continuation_id": first["continuation_id"]},
        ).json()
        assert result["continuation_id"] == first["continuation_id"]
        assert api.seerr_storage.get_continuation(first["continuation_id"])


@pytest.mark.parametrize(
    "fields",
    [
        {
            "question": 'Acquire the movie "Example Film (2026)" for the household library.'
        },
        {"question": "get it", "intent": "acquire", "title": "Example Film (2026)"},
        {
            "question": "get it",
            "intent": "acquire",
            "title": "Example Film",
            "year": 2026,
        },
    ],
)
def test_separate_year_and_question_only_compatibility(client, services, fields):
    result = client.post("/investigate", json=fields).json()
    assert result["observations"][0]["media_id"] == 22
    services[0].assert_called_once_with("Example Film")


@pytest.mark.parametrize(
    "availability,requests,reason",
    [
        ("available", [], "already_available"),
        ("pending", [], "already_in_progress"),
        ("unknown", [{"id": 3}], "already_requested"),
    ],
)
def test_nonrequestable_movie(client, services, availability, requests, reason):
    services[1].return_value = {
        "availability": availability,
        "availability_4k": "unknown",
        "mediaInfo": {"requests": requests},
    }
    result = client.post(
        "/investigate",
        json={
            "question": "get it",
            "intent": "acquire",
            "title": "Example Film",
            "year": 2026,
        },
    ).json()
    assert result["observations"][0]["reason"] == reason


def test_no_match(client, services):
    services[0].return_value = {"complete": True, "results": []}
    result = client.post("/investigate", json={"question": "get Nothing"}).json()
    assert result["continuation_id"] is None
    assert "No request was submitted" in result["answer"]


def test_expired_and_unknown_continuation(client):
    identifier = api.seerr_storage.create_continuation("Example Film")
    with sqlite3.connect(api.seerr_storage.database_path) as connection:
        connection.execute(
            "UPDATE acquisition_continuations SET expires_at='2000-01-01'"
        )
    for value in [identifier, "unknown"]:
        assert (
            client.post(
                "/investigate", json={"question": "2026", "continuation_id": value}
            ).status_code
            == 400
        )


def test_changed_candidate_identity_is_rejected(client, services):
    first = client.post("/investigate", json={"question": "get Example Film"}).json()
    services[0].return_value["results"][1]["id"] = 99
    result = client.post(
        "/investigate",
        json={"question": "2026", "continuation_id": first["continuation_id"]},
    ).json()
    assert result["observations"][0]["reason"] == "media_identity_changed"


@pytest.mark.parametrize(
    "failure", [ValueError("context limit"), ValueError("malformed JSON")]
)
def test_model_failure_is_bounded(client, failure):
    with patch.object(api.PlaneLocketAgent, "investigate", side_effect=failure):
        response = client.post(
            "/investigate",
            json={"question": "What do we own?", "intent": "investigate"},
        )
    assert response.status_code == 200
    assert response.json()["completed"] is False


def test_read_only_intent_does_not_bind_acquisition(client, services):
    from planelocket_agent.reasoning import ReasoningResult

    services[3].return_value = ReasoningResult(
        answer="Evidence", observations=(), tool_calls=0, completed=True
    )
    result = client.post(
        "/investigate",
        json={
            "question": "Is Example Film available to download?",
            "intent": "investigate",
        },
    ).json()
    assert result["answer"] == "Evidence"
    services[0].assert_not_called()


def test_continuation_migration_and_atomic_consumption(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE acquisition_continuations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
        )
    storage = SeerrRequestStorage(path)
    storage.initialize()
    storage.initialize()
    candidates = [
        {"title": "Example", "year": "2026", "media_id": 22, "media_type": "movie"}
    ]
    identifier = storage.create_continuation("Example", candidates)
    assert storage.get_continuation(identifier)["candidates"] == candidates
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(storage.consume_continuation, [identifier] * 4))
    assert sum(result is not None for result in results) == 1


def test_ambiguous_titles_never_submit_even_when_policy_enabled(
    client, services, monkeypatch
):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    result = client.post("/investigate", json={"question": "get Example Film"}).json()
    assert result["continuation_id"]
    assert result["observations"][0]["authorized"] is False


def test_original_title_article_is_preserved(client, services):
    client.post("/investigate", json={"question": "Get The Example Film"})
    services[0].assert_called_once_with("The Example Film")


def test_read_only_continuation_cannot_acquire(client, services):
    first = client.post("/investigate", json={"question": "get Example Film"}).json()
    response = client.post(
        "/investigate",
        json={
            "question": "2026",
            "intent": "investigate",
            "continuation_id": first["continuation_id"],
        },
    )
    assert response.status_code == 422
    assert api.seerr_storage.get_continuation(first["continuation_id"])


def test_duplicate_newest_year_needs_clarification(client, services):
    services[0].return_value["results"].append(
        {
            "title": "Example Film",
            "mediaType": "movie",
            "id": 33,
            "releaseDate": "2026-02-01",
        }
    )
    first = client.post("/investigate", json={"question": "get Example Film"}).json()
    result = client.post(
        "/investigate",
        json={"question": "the new one", "continuation_id": first["continuation_id"]},
    ).json()
    assert result["continuation_id"] == first["continuation_id"]
    assert "unique" in result["answer"]


def test_conflicting_years_are_not_searched(client, services):
    result = client.post(
        "/investigate",
        json={
            "question": "get it",
            "intent": "acquire",
            "title": "Example Film (1984)",
            "year": 2026,
        },
    ).json()
    assert result["observations"][0]["reason"] == "conflicting_year"
    services[0].assert_not_called()
