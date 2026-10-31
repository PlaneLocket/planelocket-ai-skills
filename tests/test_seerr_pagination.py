"""Full pagination is required even when an early page has an exact match."""

from threading import Barrier, Lock
from unittest.mock import patch

import pytest

from planelocket_agent.integrations import seerr, seerr_resolver
from planelocket_agent.integrations.seerr_workflow import prepare_movie_request


def page(number, count=1296):
    return {
        "page": number,
        "totalResults": count,
        "totalPages": max(1, (count + 19) // 20),
        "results": [
            {
                "id": i,
                "mediaType": "movie",
                "title": f"Film {i}",
                "releaseDate": "2021-01-01",
            }
            for i in range((number - 1) * 20 + 1, min(number * 20, count) + 1)
        ],
    }


def test_1296_results_collect_all_65_pages_in_order():
    def fetch(endpoint, params, *, timeout):
        assert endpoint == "search" and params["query"] == "Example"
        assert 0 < timeout <= 10
        return page(params["page"])

    with patch.object(seerr, "_seerr_get", side_effect=fetch) as get:
        result = seerr.search_media("Example")
    assert result["complete"]
    assert [item["id"] for item in result["results"]] == list(range(1, 1297))
    assert get.call_count == 65


def test_page_requests_are_concurrent_and_bounded():
    barrier = Barrier(seerr.SEARCH_WORKERS)
    lock = Lock()
    active = peak = 0

    def fetch(endpoint, params, *, timeout):
        nonlocal active, peak
        if params["page"] != 1:
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=5)
            with lock:
                active -= 1
        return page(params["page"], count=140)

    with patch.object(seerr, "_seerr_get", side_effect=fetch):
        result = seerr.search_media("Example")
    assert result["complete"]
    assert peak == seerr.SEARCH_WORKERS


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "wrong_page", "changed_count", "failed"]
)
def test_partial_or_changing_search_never_authorizes(defect, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")

    def fetch(endpoint, params, *, timeout):
        number = params["page"]
        response = page(number, count=240)
        response["results"][0]["title"] = "Example" if number == 1 else "Other"
        if number == 2:
            if defect == "missing":
                response["results"] = []
            if defect == "duplicate":
                response["results"][0]["id"] = 1
            if defect == "wrong_page":
                response["page"] = 1
            if defect == "changed_count":
                response["totalResults"] = 241
            if defect == "failed":
                raise RuntimeError("upstream failure")
        return response

    with (
        patch.object(seerr, "_seerr_get", side_effect=fetch),
        patch("planelocket_agent.integrations.seerr_workflow.request_movie") as submit,
        patch.object(seerr_resolver, "get_media_details") as details,
    ):
        outcome = prepare_movie_request("Example", year=2021)
    assert outcome["authorized"] is False
    assert outcome["reason"] == "search_too_broad"
    details.assert_not_called()
    submit.assert_not_called()


def test_duplicate_exact_title_on_later_page_stays_ambiguous(monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")

    def fetch(endpoint, params, *, timeout):
        response = page(params["page"], count=240)
        if params["page"] in (1, 12):
            response["results"][0]["title"] = "Example"
        return response

    with (
        patch.object(seerr, "_seerr_get", side_effect=fetch),
        patch("planelocket_agent.integrations.seerr_workflow.request_movie") as submit,
    ):
        result = prepare_movie_request("Example", year=2021)
    assert result["reason"] == "no_unique_match"
    assert len(result["inspection"]["candidates"]) == 2
    submit.assert_not_called()


def test_broad_search_reaches_existing_availability(monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")

    def fetch(endpoint, params, *, timeout):
        response = page(params["page"])
        if params["page"] == 1:
            response["results"][0]["title"] = "Example"
        return response

    with (
        patch.object(seerr, "_seerr_get", side_effect=fetch),
        patch.object(
            seerr_resolver,
            "get_media_details",
            return_value={
                "availability": "available",
                "availability_4k": "unknown",
                "mediaInfo": {},
            },
        ),
        patch("planelocket_agent.integrations.seerr_workflow.request_movie") as submit,
    ):
        result = prepare_movie_request("Example", year=2021)
    assert result["reason"] == "already_available"
    submit.assert_not_called()


def test_result_limit_returns_incomplete_without_fetching_more():
    with patch.object(seerr, "_seerr_get", return_value=page(1, count=2001)) as get:
        result = seerr.search_media("Example")
    assert not result["complete"] and result["results"] == []
    assert get.call_count == 1


def test_deadline_stops_before_queuing_more_pages():
    with (
        patch.object(seerr, "_seerr_get", return_value=page(1, count=240)) as get,
        patch.object(seerr.time, "monotonic", side_effect=[0, 0, 41]),
    ):
        result = seerr.search_media("Example")
    assert not result["complete"]
    assert result["incomplete_reason"] == "search_timeout"
    assert get.call_count == 1


def test_single_page_and_empty_search():
    for count in (0, 1, 20):
        with patch.object(seerr, "_seerr_get", return_value=page(1, count=count)):
            assert seerr.search_media("Example")["complete"]


def test_1296_entries_with_50_repeated_identities():
    """Reproduce the live count shape without treating one object as two movies."""
    entries = [
        {
            "id": i,
            "mediaType": "movie",
            "title": f"Film {i}",
            "releaseDate": "2021-01-01",
        }
        for i in range(1, 1247)
    ]
    entries.extend(dict(item) for item in entries[:50])

    def fetch(endpoint, params, *, timeout):
        number = params["page"]
        response = page(number)
        response["results"] = entries[(number - 1) * 20 : number * 20]
        return response

    with patch.object(seerr, "_seerr_get", side_effect=fetch):
        result = seerr.search_media("Example")
    assert result["complete"]
    assert result["total_results"] == 1296
    assert result["unique_results"] == 1246
    assert result["duplicates_omitted"] == 50
    assert [item["id"] for item in result["results"]] == list(range(1, 1247))


@pytest.mark.parametrize("field", ["title", "originalTitle", "releaseDate"])
def test_conflicting_data_for_one_identity_stays_incomplete(field):
    def fetch(endpoint, params, *, timeout):
        response = page(params["page"], count=40)
        if params["page"] == 2:
            response["results"][0] = dict(page(1, count=40)["results"][0])
            response["results"][0][field] = "conflicting data"
        return response

    with patch.object(seerr, "_seerr_get", side_effect=fetch):
        result = seerr_resolver.find_media("Film 1", media_type="movie", year=2021)
    assert not result["resolved"]
    assert result["search"]["incomplete_reason"] == "conflicting_identity"


def test_same_number_across_media_types_is_not_deduplicated():
    response = page(1, count=2)
    response["results"][1] = {
        "id": 1,
        "mediaType": "tv",
        "name": "Film 1",
        "firstAirDate": "2021-01-01",
    }
    with patch.object(seerr, "_seerr_get", return_value=response):
        result = seerr.search_media("Film 1")
    assert result["complete"]
    assert result["unique_results"] == 2


def test_repeated_exact_candidate_reaches_available_status(monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")
    response = page(1, count=2)
    response["results"][1] = dict(response["results"][0])
    with (
        patch.object(seerr, "_seerr_get", return_value=response),
        patch.object(
            seerr_resolver,
            "get_media_details",
            return_value={
                "availability": "available",
                "availability_4k": "unknown",
                "mediaInfo": {},
            },
        ),
        patch("planelocket_agent.integrations.seerr_workflow.request_movie") as submit,
    ):
        result = prepare_movie_request("Film 1", year=2021)
    assert result["reason"] == "already_available"
    submit.assert_not_called()
