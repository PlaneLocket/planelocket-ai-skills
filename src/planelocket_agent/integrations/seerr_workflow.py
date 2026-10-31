"""Coordinate Seerr movie requests."""

import re

from planelocket_agent.integrations.seerr import (
    get_media_details,
    request_movie,
)
from planelocket_agent.integrations.seerr_policy import (
    evaluate_movie_request,
)
from planelocket_agent.integrations.seerr_resolver import inspect_media
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


def prepare_movie_request(
    title: str,
    year: int | None = None,
    storage: SeerrRequestStorage | None = None,
    expected_media_id: int | None = None,
) -> dict:
    """Resolve a movie and determine whether acquisition is permitted."""

    # Split a display title from its release year before asking Seerr to search.
    match = re.fullmatch(r"(.+?)\s+\(((?:19|20)\d{2})\)", title.strip())
    if match:
        if year is not None and year != int(match[2]):
            return {
                "authorized": False,
                "reason": "conflicting_year",
                "inspection": {},
                "continuation_id": None,
            }
        title, year = match[1], int(match[2])

    inspection = inspect_media(
        title,
        media_type="movie",
        year=year,
    )

    if (
        expected_media_id is not None
        and inspection.get("resolved")
        and inspection["media"]["id"] != expected_media_id
    ):
        return {
            "authorized": False,
            "reason": "media_identity_changed",
            "inspection": inspection,
            "continuation_id": None,
        }

    if (
        not inspection["resolved"]
        and inspection["reason"] == "no_unique_match"
        and len(inspection.get("candidates", [])) > 1
        and storage is not None
    ):
        continuation_id = storage.create_continuation(title, inspection["candidates"])
    else:
        continuation_id = None

    decision = evaluate_movie_request(
        inspection,
        explicit_acquisition_intent=True,
    )

    if decision["authorized"]:
        decision["submission"] = submit_movie_request(decision["media_id"])
    elif decision["reason"] == "auto_request_disabled":
        decision["submission"] = {
            "submitted": False,
            "reason": "dry_run",
        }

    return {
        **decision,
        "inspection": inspection,
        "continuation_id": continuation_id,
    }


def submit_movie_request(media_id: int) -> dict:
    """Recheck availability before submitting a movie request."""

    details = get_media_details("movie", media_id)

    if details["availability"] != "unknown":
        return {
            "submitted": False,
            "reason": "media_not_requestable",
        }

    media_info = details.get("mediaInfo") or {}

    if media_info.get("requests"):
        return {
            "submitted": False,
            "reason": "already_requested",
        }

    response = request_movie(media_id)

    return {
        "submitted": True,
        "request_id": response["id"],
    }


def confirm_movie_request(
    request_id: str,
    storage: SeerrRequestStorage,
) -> dict:
    """Submit a previously prepared and confirmed movie request."""

    from planelocket_agent.integrations.seerr_policy import auto_request_enabled

    if not auto_request_enabled():
        return {"submitted": False, "reason": "dry_run"}

    if not storage.claim_pending(request_id):
        return {
            "submitted": False,
            "reason": "invalid_or_expired_request",
        }

    record = storage.get_request(request_id)

    try:
        result = submit_movie_request(record["media_id"])
    except Exception:
        storage.mark_uncertain(request_id)
        raise

    if not result["submitted"]:
        storage.mark_failed(request_id)
        return result

    storage.mark_submitted(
        request_id,
        result["request_id"],
    )

    return result
