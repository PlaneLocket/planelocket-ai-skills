"""Architecture acceptance: frontend knows the wire contract, not providers."""

import ast
import re
from pathlib import Path

import pytest

from custom_components.planelocket_ai.client import PlaneLocketError, bounded_result


@pytest.mark.parametrize(
    "outcome,action",
    [
        ("completed", "respond"),
        ("clarification_required", "clarify"),
        ("blocked", "stop"),
        ("uncertain", "stop"),
    ],
)
def test_control_survives_unknown_provider_fields_and_truncation(evidence, outcome, action):
    evidence["control"] = {"version": 1, "outcome": outcome, "next_action": action, "partial": True}
    evidence["answer"] = "The backend decision is authoritative."
    evidence["observations"] = [
        {
            "provider": "NewProvider2099",
            "state": "BrandNewState",
            "submission": {"submitted": None},
            "huge": "x" * 30000,
        }
    ]
    result = bounded_result(evidence, "test-token")
    assert result["control"] == evidence["control"]
    assert result["answer"] == evidence["answer"]
    assert result["observations_omitted"] == 1


@pytest.mark.parametrize(
    "control",
    [
        None,
        {},
        {"version": True, "outcome": "completed", "next_action": "respond", "partial": False},
        {"version": 2, "outcome": "completed", "next_action": "respond", "partial": False},
        {"version": 1, "outcome": "uncertain", "next_action": "respond", "partial": False},
        {"version": 1, "outcome": "new_status", "next_action": "respond", "partial": False},
    ],
)
def test_missing_or_invalid_protocol_never_causes_inferred_success(evidence, control):
    evidence["control"] = control
    with pytest.raises(PlaneLocketError, match="invalid_response"):
        bounded_result(evidence, "test-token")


def test_adapter_contains_no_provider_lifecycle_or_capability_rules():
    root = Path(__file__).parents[1] / "custom_components" / "planelocket_ai"
    forbidden = (
        "seerr",
        "lazylibrarian",
        "cwng",
        "nextgen",
        "wanted",
        "snatched",
        "AUTO_REQUEST",
        "EPUB",
        "MOBI",
        "PDF",
    )
    evidence_keys = {"submission", "reason", "authorized", "requestable_seasons"}
    for name in ("client.py", "llm_api.py"):
        source = (root / name).read_text()
        for term in forbidden:
            assert term.casefold() not in source.casefold(), (name, term)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in evidence_keys, (name, node.value)
                if name == "llm_api.py":
                    assert node.value != "observations", (
                        "Tool dispatch must not inspect provider evidence"
                    )
                assert not re.search(r"\bsearchBook\b", node.value, re.IGNORECASE), name
