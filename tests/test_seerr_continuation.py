"""Regression tests for ambiguous movie acquisition continuations."""

from unittest.mock import patch

from planelocket_agent.integrations.seerr_workflow import prepare_movie_request
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


def test_ambiguous_acquisition_returns_continuation(tmp_path, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")
    storage = SeerrRequestStorage(tmp_path / "seerr.sqlite3")
    storage.initialize()
    inspection = {
        "resolved": False,
        "reason": "no_unique_match",
        "media": None,
        "candidates": [
            {"title": "Supergirl", "year": "1984", "media_id": 9651},
            {"title": "Supergirl", "year": "2026", "media_id": 1081003},
        ],
    }
    with patch(
        "planelocket_agent.integrations.seerr_workflow.inspect_media",
        return_value=inspection,
    ), patch(
        "planelocket_agent.integrations.seerr_workflow.submit_movie_request"
    ) as submit:
        result = prepare_movie_request("Supergirl", storage=storage)

    assert result["reason"] == "no_unique_match"
    assert result["continuation_id"]
    assert storage.get_continuation(result["continuation_id"])["title"] == "Supergirl"
    submit.assert_not_called()


def test_no_match_does_not_create_continuation(tmp_path, monkeypatch):
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "false")
    storage = SeerrRequestStorage(tmp_path / "seerr.sqlite3")
    storage.initialize()
    with patch(
        "planelocket_agent.integrations.seerr_workflow.inspect_media",
        return_value={
            "resolved": False, "reason": "no_unique_match",
            "media": None, "candidates": [],
        },
    ):
        result = prepare_movie_request("Nonexistent Film", storage=storage)
    assert result["continuation_id"] is None
