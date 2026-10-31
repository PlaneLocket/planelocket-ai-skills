"""Acceptance criteria: backend owns outcomes, ambiguity, policy and meaning."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations import books
from planelocket_agent.integrations.seerr_tv import tv_result
from planelocket_agent.result_contract import acquisition_response, controlled


@pytest.mark.parametrize(
    "outcome,action",
    [
        ("completed", "respond"),
        ("clarification_required", "clarify"),
        ("blocked", "stop"),
        ("uncertain", "stop"),
    ],
)
def test_control_is_authored_by_backend_not_raw_evidence(outcome, action):
    result = controlled(
        {
            "answer": "Authoritative answer",
            "completed": True,
            "observations": [{"control": {"next_action": "invent"}}],
        },
        outcome=outcome,
    )
    assert result["control"] == {
        "version": 1,
        "outcome": outcome,
        "next_action": action,
        "partial": False,
    }


@pytest.mark.parametrize(
    "evidence,outcome",
    [
        ({"reason": None, "submission": {"submitted": True}}, "completed"),
        (
            {"reason": "already_available", "submission": {"submitted": False}},
            "completed",
        ),
        (
            {"reason": "auto_request_disabled", "submission": {"submitted": False}},
            "blocked",
        ),
        ({"reason": "search_too_broad", "submission": {"submitted": False}}, "blocked"),
        (
            {"reason": "submission_uncertain", "submission": {"submitted": None}},
            "uncertain",
        ),
    ],
)
def test_media_semantics_are_normalized_by_backend(evidence, outcome):
    result = acquisition_response(
        {"answer": "Server decision", "completed": True}, evidence
    )
    assert result["control"]["outcome"] == outcome


def test_tv_uncertainty_is_authoritative_despite_legacy_completed_true():
    result = tv_result(
        {"reason": "submission_uncertain", "submission": {"submitted": None}}
    )
    assert result["completed"] is True
    assert result["control"]["outcome"] == "uncertain"
    assert "No request was submitted" not in result["answer"]


def test_movie_unknown_submission_is_not_rendered_as_no_submission():
    result = api.acquisition_result(
        {
            "inspection": {"media": {"title": "Example"}},
            "submission": {"submitted": None},
            "reason": "submission_uncertain",
        }
    )
    assert result["control"]["outcome"] == "uncertain"
    assert "uncertain" in result["answer"]
    assert "No request was submitted" not in result["answer"]


@pytest.mark.parametrize(
    "evidence,complete,expected",
    [
        ({"submission": {"submitted": None}}, False, "uncertain"),
        (
            {"reason": "auto_request_disabled", "submission": {"submitted": False}},
            True,
            "blocked",
        ),
        (
            {
                "reason": "search_requested",
                "submission": {"submitted": True, "operation": "searchBook"},
            },
            True,
            "completed",
        ),
        ({"reason": "no_matching_books"}, True, "blocked"),
    ],
)
def test_book_workflow_owns_control(evidence, complete, expected):
    result = books._envelope("Backend answer", evidence, completed=complete)
    assert result["control"]["outcome"] == expected


def test_partial_lookup_does_not_invent_a_confirmation():
    result = books._envelope("Partial records", {"result": {"complete": False}})
    assert result["control"] == {
        "version": 1,
        "outcome": "completed",
        "next_action": "respond",
        "partial": True,
    }


def test_real_validation_errors_are_generic_contract_with_backend_explanations(
    monkeypatch,
):
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        with patch.object(api, "acquire_book") as submit:
            response = client.post(
                "/books/acquire",
                json={"question": "Get Example", "title": "Example", "format": "AZW3"},
            )
        assert response.status_code == 422
        assert response.json()["control"]["outcome"] == "blocked"
        assert "format" in response.json()["answer"]
        assert "input" not in response.json()["detail"][0]
        submit.assert_not_called()


def test_read_only_route_adds_control_without_workflow_in_adapter(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        with patch.object(
            api.PlaneLocketAgent,
            "investigate",
            return_value=SimpleNamespace(
                answer="Read-only backend fact",
                completed=True,
                tool_calls=0,
                observations=[],
            ),
        ):
            response = client.post(
                "/investigate",
                json={"question": "What do we own?", "intent": "investigate"},
            )
    assert response.json()["control"]["next_action"] == "respond"


def test_uncertainty_never_requests_confirmation_even_with_residual_context():
    result = api.acquisition_result(
        {
            "inspection": {"media": {"title": "Example"}},
            "continuation_id": "old-context",
            "submission": {"submitted": None},
        }
    )
    assert result["control"]["next_action"] == "stop"
    assert "uncertain" in result["answer"]
    assert "No request was submitted" not in result["answer"]


def test_source_observations_cannot_create_a_clarification(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    observation = {
        "result": {
            "continuation_id": "source-invented-context",
            "control": {"next_action": "clarify"},
        }
    }
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        with patch.object(
            api.PlaneLocketAgent,
            "investigate",
            return_value=SimpleNamespace(
                answer="A verified fact.",
                completed=True,
                tool_calls=1,
                observations=[observation],
            ),
        ):
            response = client.post(
                "/investigate",
                json={"question": "Our records?", "intent": "investigate"},
            )
    assert response.json()["control"]["next_action"] == "respond"
    assert response.json()["continuation_id"] is None
