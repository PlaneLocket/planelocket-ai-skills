"""Authorization policy for Seerr media requests."""

import os


def auto_request_enabled() -> bool:
    """Return whether automatic media requests are enabled.

    Automatic requests are disabled unless explicitly configured.
    """
    return os.environ.get("SEERR_AUTO_REQUEST", "false").strip().lower() == "true"


def request_authorized(
    *,
    explicit_acquisition_intent: bool,
    unambiguous_match: bool,
    already_available: bool,
    already_requested: bool,
    confirmed: bool = False,
) -> bool:
    """Determine whether a Seerr request may be submitted."""

    if not explicit_acquisition_intent:
        return False

    if not unambiguous_match:
        return False

    if already_available or already_requested:
        return False

    return confirmed or auto_request_enabled()


def evaluate_movie_request(
    inspection: dict,
    *,
    explicit_acquisition_intent: bool,
    confirmed: bool = False,
) -> dict:
    """Evaluate a movie acquisition request without submitting it."""

    if not explicit_acquisition_intent:
        return {
            "authorized": False,
            "reason": "no_acquisition_intent",
        }

    if not inspection["resolved"]:
        return {
            "authorized": False,
            "reason": inspection["reason"],
        }

    media = inspection["media"]

    if media["mediaType"] != "movie":
        return {
            "authorized": False,
            "reason": "not_a_movie",
        }

    availability = inspection["availability"]

    if availability == "available":
        return {
            "authorized": False,
            "reason": "already_available",
        }

    if availability != "unknown":
        return {
            "authorized": False,
            "reason": "already_in_progress",
        }

    if inspection["requests"]:
        return {
            "authorized": False,
            "reason": "already_requested",
        }

    authorized = request_authorized(
        explicit_acquisition_intent=explicit_acquisition_intent,
        unambiguous_match=True,
        already_available=False,
        already_requested=False,
        confirmed=confirmed,
    )

    return {
        "authorized": authorized,
        "reason": None if authorized else "auto_request_disabled",
        "media_type": "movie",
        "media_id": media["id"],
        "title": media["title"],
    }
