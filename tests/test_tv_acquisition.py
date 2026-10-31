"""TV acquisition uses typed show identity, explicit scope and per-season policy."""

import copy
import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations import seerr_tv
from planelocket_agent.integrations.seerr import request_tv
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-only-token")
    store = SeerrRequestStorage(tmp_path / "requests.sqlite3")
    store.initialize()
    monkeypatch.setattr(api, "seerr_storage", store)
    with TestClient(
        api.app, headers={"Authorization": "Bearer test-only-token"}
    ) as client:
        yield client


@pytest.fixture
def services():
    series = {
        "id": 101,
        "mediaType": "tv",
        "name": "Example Series",
        "firstAirDate": "2020-01-01",
    }
    details = {
        "id": 101,
        "name": "Example Series",
        "firstAirDate": "2020-01-01",
        "seasons": [
            {"seasonNumber": number, "episodeCount": 10, "name": f"Season {number}"}
            for number in (0, 1, 2, 3)
        ],
        "mediaInfo": None,
    }
    with (
        patch(
            "planelocket_agent.integrations.seerr_resolver.search_media",
            return_value={"complete": True, "results": [series]},
        ) as search,
        patch.object(seerr_tv, "get_media_details", return_value=details) as inspect,
        patch.object(seerr_tv, "request_tv") as submit,
        patch.object(api.PlaneLocketAgent, "investigate") as agent,
    ):
        yield search, inspect, submit, agent


def post(client, **fields):
    return client.post(
        "/investigate",
        json={
            "question": "Get Example Series",
            "title": "Example Series",
            "intent": "acquire",
            "media_type": "tv",
            **fields,
        },
    )


def test_selected_seasons_dry_run(client, services):
    response = post(client, year=2020, seasons=[2, 1])
    assert response.status_code == 200
    result = response.json()
    outcome = result["observations"][0]
    assert outcome["media_id"] == 101
    assert outcome["requested_seasons"] == [1, 2]
    assert outcome["requestable_seasons"] == [1, 2]
    assert outcome["submission"] == {"submitted": False, "reason": "dry_run"}
    assert "No request was submitted" in result["answer"]
    services[0].assert_called_once_with("Example Series")
    services[2].assert_not_called()
    services[3].assert_not_called()


@pytest.mark.parametrize(
    "reply,selection",
    [
        ("season 2", [2]),
        ("seasons 1 and 3", [1, 3]),
        ("1-3", [1, 2, 3]),
        ("all seasons", [1, 2, 3]),
        ("season 0", [0]),
    ],
)
def test_season_clarification_and_replay(client, services, reply, selection):
    first = post(client).json()
    identifier = first["continuation_id"]
    assert identifier and "which seasons" in first["answer"]
    record = api.seerr_storage.get_continuation(identifier)
    assert record["context"]["media_type"] == "tv"
    result = post(client, question=reply, continuation_id=identifier).json()
    assert result["observations"][0]["requested_seasons"] == selection
    assert api.seerr_storage.get_continuation(identifier) is None
    assert post(client, question=reply, continuation_id=identifier).status_code == 400
    services[2].assert_not_called()


def test_show_year_selection_then_season_selection(client, services):
    newer = services[0].return_value["results"][0]
    older = {**newer, "id": 99, "firstAirDate": "1990-01-01"}
    services[0].return_value["results"].append(older)
    first = post(client).json()
    assert "1990" in first["answer"] and "2020" in first["answer"]
    second = post(
        client, question="2020", year=2020, continuation_id=first["continuation_id"]
    ).json()
    assert (
        second["continuation_id"]
        and second["continuation_id"] != first["continuation_id"]
    )
    assert "which seasons" in second["answer"]
    third = post(
        client,
        question="season 2",
        seasons=[2],
        continuation_id=second["continuation_id"],
    ).json()
    assert third["observations"][0]["media_id"] == 101
    assert third["observations"][0]["requested_seasons"] == [2]


@pytest.mark.parametrize("reply", ["2020", "the new one", "latest"])
def test_ambiguous_show_preserves_scope(client, services, reply):
    original = services[0].return_value["results"][0]
    services[0].return_value["results"].append(
        {**original, "id": 99, "firstAirDate": "1990-01-01"}
    )
    first = post(client, seasons=[2]).json()
    second = post(
        client, question=reply, continuation_id=first["continuation_id"]
    ).json()
    assert second["observations"][0]["requested_seasons"] == [2]
    assert second["observations"][0]["media_id"] == 101


def test_all_scope_survives_show_disambiguation(client, services):
    original = services[0].return_value["results"][0]
    services[0].return_value["results"].append(
        {**original, "id": 99, "firstAirDate": "1990-01-01"}
    )
    first = post(client, all_seasons=True).json()
    second = post(
        client, question="2020", continuation_id=first["continuation_id"]
    ).json()
    assert second["observations"][0]["requested_seasons"] == [1, 2, 3]


def test_mixed_per_season_status(client, services):
    services[1].return_value["mediaInfo"] = {
        "status": 4,
        "seasons": [{"seasonNumber": 1, "status": 5}, {"seasonNumber": 2, "status": 1}],
        "requests": [{"status": 2, "is4k": False, "seasons": [{"seasonNumber": 3}]}],
    }
    result = post(client, all_seasons=True).json()["observations"][0]
    assert result["available_seasons"] == [1]
    assert result["already_requested_seasons"] == [3]
    assert result["requestable_seasons"] == [2]
    assert result["reason"] == "auto_request_disabled"
    services[2].assert_not_called()


@pytest.mark.parametrize(
    "state,reason",
    [
        (5, "already_available"),
        (2, "already_in_progress"),
        (3, "already_in_progress"),
        (4, "already_in_progress"),
        (6, "blocklisted"),
        (999, "unverified_season_status"),
    ],
)
def test_season_status_blocks_submission(client, services, monkeypatch, state, reason):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = {
        "requests": [],
        "status": 4,
        "seasons": [{"seasonNumber": 2, "status": state}],
    }
    result = post(client, seasons=[2]).json()["observations"][0]
    assert result["reason"] == reason
    services[2].assert_not_called()


def test_existing_request_seasons_do_not_block_other_seasons(client, services):
    services[1].return_value["mediaInfo"] = {
        "seasons": [],
        "status": 2,
        "requests": [{"status": 1, "seasons": [{"seasonNumber": 1}]}],
    }
    assert (
        post(client, seasons=[1]).json()["observations"][0]["reason"]
        == "already_requested"
    )
    assert post(client, seasons=[2]).json()["observations"][0][
        "requestable_seasons"
    ] == [2]


@pytest.mark.parametrize(
    "existing_request",
    [
        {"status": 3, "seasons": [{"seasonNumber": 2}]},
        {"status": 5, "seasons": [{"seasonNumber": 2}]},
        {"status": 2, "is4k": True, "seasons": [{"seasonNumber": 2}]},
    ],
)
def test_nonholding_requests_do_not_block_standard_season(
    client, services, existing_request
):
    services[1].return_value["mediaInfo"] = {
        "seasons": [],
        "status": 1,
        "requests": [existing_request],
    }
    assert post(client, seasons=[2]).json()["observations"][0][
        "requestable_seasons"
    ] == [2]


def test_authorized_mock_submission_only_missing_seasons(client, services, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = {
        "requests": [],
        "status": 4,
        "seasons": [{"seasonNumber": 1, "status": 5}],
    }
    services[2].return_value = {
        "id": 12,
        "seasons": [{"seasonNumber": 2}, {"seasonNumber": 3}],
    }
    response = post(client, all_seasons=True).json()
    services[2].assert_called_once_with(101, [2, 3])
    assert response["observations"][0]["submission"]["submitted"] is True
    assert "Requested Example Series" in response["answer"]


def test_availability_rechecked_before_post(client, services, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    before = copy.deepcopy(services[1].return_value)
    after = copy.deepcopy(before)
    after["mediaInfo"] = {
        "requests": [],
        "status": 5,
        "seasons": [{"seasonNumber": 2, "status": 5}],
    }
    services[1].side_effect = [before, after]
    result = post(client, seasons=[2]).json()
    assert result["observations"][0]["submission"]["submitted"] is False
    assert "No request was submitted" in result["answer"]
    services[2].assert_not_called()


def test_policy_rechecked_before_post(client, services):
    with patch.object(seerr_tv, "request_authorized", side_effect=[True, False]):
        result = post(client, seasons=[2]).json()
    assert result["observations"][0]["submission"] == {
        "submitted": False,
        "reason": "dry_run",
    }
    services[2].assert_not_called()


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError("no acknowledgement"),
        {},
        {"id": 4},
        {"id": 4, "seasons": [{"seasonNumber": 999}]},
    ],
)
def test_post_uncertainty_is_not_claimed_as_failure_or_retried(
    client, services, monkeypatch, response
):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    if isinstance(response, Exception):
        services[2].side_effect = response
    else:
        services[2].return_value = response
    result = post(client, seasons=[2]).json()
    assert result["observations"][0]["submission"]["submitted"] is None
    assert "uncertain" in result["answer"]
    assert "No request was submitted" not in result["answer"]
    assert services[2].call_count == 1


@pytest.mark.parametrize(
    "scope",
    [
        {"seasons": []},
        {"seasons": [True]},
        {"seasons": ["2"]},
        {"seasons": [-1]},
        {"seasons": [1000]},
        {"seasons": [1, 1]},
        {"seasons": [1], "all_seasons": True},
        {"all_seasons": "true"},
    ],
)
def test_invalid_scope_never_calls_external_services(client, services, scope):
    assert post(client, **scope).status_code == 422
    services[0].assert_not_called()
    services[2].assert_not_called()


def test_bad_selection_reissues_season_clarification(client, services):
    result = post(client, seasons=[99]).json()
    assert result["continuation_id"]
    assert result["observations"][0]["reason"] == "invalid_season_selection"
    services[2].assert_not_called()


def test_expired_tv_continuation(client, services):
    identifier = post(client).json()["continuation_id"]
    with sqlite3.connect(api.seerr_storage.database_path) as connection:
        connection.execute(
            "UPDATE acquisition_continuations SET expires_at='2000-01-01'"
        )
    assert post(client, seasons=[2], continuation_id=identifier).status_code == 400
    services[2].assert_not_called()


def test_movie_tv_continuation_cannot_be_mixed(client, services):
    tv_id = post(client).json()["continuation_id"]
    assert (
        client.post(
            "/investigate",
            json={"question": "2020", "intent": "acquire", "continuation_id": tv_id},
        ).status_code
        == 422
    )
    movie_id = api.seerr_storage.create_continuation("Example Film", [])
    assert post(client, seasons=[2], continuation_id=movie_id).status_code == 400
    assert api.seerr_storage.get_continuation(tv_id)
    assert api.seerr_storage.get_continuation(movie_id)


def test_continuation_cannot_change_show(client, services):
    identifier = post(client).json()["continuation_id"]
    result = post(
        client,
        question="season 2",
        title="Different Show",
        seasons=[2],
        continuation_id=identifier,
    ).json()
    assert result["observations"][0]["title"] == "Example Series"
    assert services[0].call_args.args == ("Example Series",)


def test_changed_resolved_identity_blocks_resume(client, services):
    identifier = post(client).json()["continuation_id"]
    services[0].return_value["results"][0]["id"] = 999
    result = post(client, seasons=[2], continuation_id=identifier).json()
    assert result["observations"][0]["reason"] == "media_identity_changed"
    services[2].assert_not_called()


def test_unknown_reply_keeps_continuation(client, services):
    identifier = post(client).json()["continuation_id"]
    result = post(client, question="yes", continuation_id=identifier).json()
    assert result["continuation_id"] == identifier
    assert api.seerr_storage.get_continuation(identifier)


def test_no_match_and_incomplete_search_never_submit(client, services):
    for search in [
        {"complete": True, "results": []},
        {"complete": False, "results": [], "incomplete_reason": "page_failed"},
    ]:
        services[0].return_value = search
        result = post(client, seasons=[2]).json()
        assert result["observations"][0]["authorized"] is False
    services[2].assert_not_called()


def test_tv_requires_explicit_acquisition_intent(client, services):
    assert post(client, intent="investigate", seasons=[2]).status_code == 422
    services[0].assert_not_called()


def test_transport_only_posts_explicit_season_list():
    with patch(
        "planelocket_agent.integrations.seerr._seerr_post", return_value={"id": 2}
    ) as submit:
        assert request_tv(101, [2, 0]) == {"id": 2}
    submit.assert_called_once_with(
        "request", {"mediaType": "tv", "mediaId": 101, "seasons": [0, 2], "is4k": False}
    )


def test_storage_migration_keeps_old_movie_continuations(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE acquisition_continuations (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, candidates TEXT NOT NULL DEFAULT '[]')"
        )
        connection.execute(
            "INSERT INTO acquisition_continuations VALUES ('old', 'Example', '2020-01-01', '2999-01-01', '[]')"
        )
    storage = SeerrRequestStorage(path)
    storage.initialize()
    storage.initialize()
    assert storage.get_continuation("old")["context"] == {}
    assert storage.consume_continuation("old")["title"] == "Example"


def test_parenthesized_show_year_and_conflict(client, services):
    result = post(client, title="Example Series (2020)", seasons=[2]).json()
    assert result["observations"][0]["media_id"] == 101
    services[0].assert_called_once_with("Example Series")
    result = post(client, title="Example Series (2020)", year=1990, seasons=[2]).json()
    assert result["observations"][0]["reason"] == "conflicting_year"


def test_equal_newest_year_candidates_stay_ambiguous(client, services):
    original = services[0].return_value["results"][0]
    services[0].return_value["results"].append({**original, "id": 999})
    first = post(client, seasons=[2]).json()
    result = post(
        client, question="the new one", continuation_id=first["continuation_id"]
    ).json()
    assert result["continuation_id"] == first["continuation_id"]
    services[1].assert_not_called()
    services[2].assert_not_called()


def test_empty_catalog_does_not_ask_unanswerable_question(client, services):
    services[1].return_value["seasons"] = []
    result = post(client).json()
    assert result["observations"][0]["reason"] == "no_seasons_available"
    assert result["continuation_id"] is None


def test_season_without_episodes_never_submits(client, services, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["seasons"][2]["episodeCount"] = 0
    result = post(client, seasons=[2]).json()
    assert result["observations"][0]["reason"] == "season_has_no_episodes"
    services[2].assert_not_called()


def test_incomplete_status_data_never_submits(client, services, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = {"seasons": [], "requests": [], "status": 5}
    result = post(client, seasons=[2]).json()
    assert result["observations"][0]["reason"] == "unverified_season_status"
    services[2].assert_not_called()


def test_series_blocklist_never_submits(client, services, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = {"seasons": [], "requests": [], "status": 6}
    assert (
        post(client, seasons=[2]).json()["observations"][0]["reason"] == "blocklisted"
    )
    services[2].assert_not_called()


def test_detail_failure_is_honest_incomplete_result(client, services):
    services[1].side_effect = RuntimeError("remote failure")
    result = post(client, seasons=[2]).json()
    assert result["completed"] is False
    assert "No request was submitted" in result["answer"]
    services[2].assert_not_called()


def test_changed_detail_identity_never_submits(client, services):
    services[1].return_value["name"] = "Different Series"
    assert (
        post(client, seasons=[2]).json()["observations"][0]["reason"]
        == "media_identity_changed"
    )
    services[2].assert_not_called()


def test_special_season_requires_explicit_scope(client, services):
    assert post(client, all_seasons=True).json()["observations"][0][
        "requested_seasons"
    ] == [1, 2, 3]
    assert post(client, seasons=[0]).json()["observations"][0]["requested_seasons"] == [
        0
    ]


def test_catalog_change_before_post_does_not_expand_all_scope(
    client, services, monkeypatch
):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    before = copy.deepcopy(services[1].return_value)
    after = copy.deepcopy(before)
    after["seasons"].append({"seasonNumber": 4, "episodeCount": 10})
    services[1].side_effect = [before, after]
    services[2].return_value = {
        "id": 3,
        "seasons": [{"seasonNumber": n} for n in (1, 2, 3)],
    }
    post(client, all_seasons=True)
    services[2].assert_called_once_with(101, [1, 2, 3])


@pytest.mark.parametrize(
    "info", [[], False, {"status": 2, "requests": [{"status": 2, "seasons": []}]}]
)
def test_malformed_season_state_never_submits(client, services, monkeypatch, info):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = info
    result = post(client, seasons=[2]).json()
    assert result["observations"][0]["reason"] == "unverified_season_status"
    services[2].assert_not_called()


def test_all_seasons_without_episode_bearing_regular_seasons(client, services):
    for item in services[1].return_value["seasons"]:
        item["episodeCount"] = 0
    result = post(client, all_seasons=True).json()
    assert result["observations"][0]["reason"] == "no_regular_seasons_available"
    assert result["continuation_id"] is None
    services[2].assert_not_called()


def test_all_seasons_over_batch_limit_asks_for_smaller_selection(client, services):
    services[1].return_value["seasons"] = [
        {"seasonNumber": number, "episodeCount": 10} for number in range(1, 102)
    ]
    result = post(client, all_seasons=True).json()
    assert result["observations"][0]["reason"] == "invalid_season_selection"
    assert result["continuation_id"]
    services[2].assert_not_called()


@pytest.mark.parametrize(
    "info", [{}, {"status": 4, "seasons": []}, {"status": 2, "requests": []}]
)
def test_omitted_media_state_fields_cannot_authorize(
    client, services, monkeypatch, info
):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    services[1].return_value["mediaInfo"] = info
    assert (
        post(client, seasons=[2]).json()["observations"][0]["reason"]
        == "unverified_season_status"
    )
    services[2].assert_not_called()
