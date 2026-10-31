"""Provider-independent interaction contract authored by the backend."""

NEXT_ACTION = {
    "completed": "respond",
    "clarification_required": "clarify",
    "blocked": "stop",
    "uncertain": "stop",
}


def controlled(result, *, outcome=None, partial=False):
    """Retain legacy fields and attach authoritative interaction metadata."""
    if outcome is None:
        outcome = (
            "clarification_required"
            if result.get("continuation_id")
            else "completed"
            if result.get("completed")
            else "blocked"
        )
    if outcome not in NEXT_ACTION or type(partial) is not bool:
        raise ValueError("Invalid backend interaction control")
    return {
        **result,
        "control": {
            "version": 1,
            "outcome": outcome,
            "next_action": NEXT_ACTION[outcome],
            "partial": partial,
        },
    }


def acquisition_response(result, evidence):
    """Normalize legacy movie/TV workflow decisions inside the backend."""
    submission = evidence.get("submission", {})
    if "submitted" in submission and submission["submitted"] is None:
        outcome = "uncertain"
    elif result.get("continuation_id"):
        outcome = "clarification_required"
    elif submission.get("submitted") is True or evidence.get("reason") in {
        "already_available",
        "already_requested",
        "already_in_progress",
    }:
        outcome = "completed"
    else:
        outcome = "blocked"
    return controlled(result, outcome=outcome)
