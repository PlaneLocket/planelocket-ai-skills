"""Resolve TV identity and coordinate explicitly selected Seerr season requests."""

import re

from planelocket_agent.integrations.seerr import get_media_details, request_tv
from planelocket_agent.integrations.seerr_policy import request_authorized
from planelocket_agent.integrations.seerr_resolver import find_media, normalize_title
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage
from planelocket_agent.result_contract import acquisition_response


class TVContinuationError(ValueError):
    """A continuation is invalid, expired, mistyped, or already consumed."""


def validate_seasons(seasons, all_seasons=False):
    """Reject implicit scope expansion, boolean season numbers and mixed selectors."""
    if type(all_seasons) is not bool or (seasons is not None and all_seasons):
        raise ValueError("Choose specific seasons or all_seasons, not both")
    if seasons is not None and (
        not isinstance(seasons, list)
        or not 1 <= len(seasons) <= 100
        or any(type(number) is not int or not 0 <= number <= 999 for number in seasons)
        or len(set(seasons)) != len(seasons)
    ):
        raise ValueError("Provide 1 to 100 distinct season numbers from 0 to 999")
    return sorted(seasons) if seasons is not None else None


def _outcome(reason, inspection=None, **fields):
    return {
        "authorized": False,
        "reason": reason,
        "media_type": "tv",
        "inspection": inspection or {},
        "continuation_id": None,
        "submission": {"submitted": False, "reason": reason},
        **fields,
    }


def _catalog(details):
    seasons = details.get("seasons")
    if not isinstance(seasons, list):
        return None
    catalog = {}
    for item in seasons:
        number = item.get("seasonNumber") if isinstance(item, dict) else None
        if type(number) is not int or not 0 <= number <= 999 or number in catalog:
            return None
        if type(item.get("episodeCount")) is not int or item["episodeCount"] < 0:
            return None
        catalog[number] = {
            "season": number,
            "name": item.get("name"),
            "episode_count": item.get("episodeCount"),
            "air_date": item.get("airDate"),
        }
    return catalog


def evaluate_tv_seasons(details: dict, seasons: list[int]) -> dict:
    """Evaluate only selected seasons, independent of whole-series availability.

    Seerr MediaStatus: 1 unknown, 2 pending, 3 processing, 4 partial,
    5 available, 6 blocklisted, 7 deleted. Request statuses 1/2/4 hold
    season claims; declined (3) and completed (5) do not.
    """
    catalog = _catalog(details)
    if catalog is None:
        return {"reason": "invalid_season_catalog", "requestable_seasons": []}
    if any(number not in catalog for number in seasons):
        return {"reason": "invalid_season_selection", "requestable_seasons": []}
    if any(catalog[number]["episode_count"] == 0 for number in seasons):
        return {"reason": "season_has_no_episodes", "requestable_seasons": []}
    info = details.get("mediaInfo")
    has_media = info is not None
    if info is None:
        info = {}
    if not isinstance(info, dict):
        return {"reason": "unverified_season_status", "requestable_seasons": []}
    if has_media and (
        type(info.get("status")) is not int or info["status"] not in range(1, 8)
    ):
        return {"reason": "unverified_season_status", "requestable_seasons": []}
    if info.get("status") == 6:
        return {"reason": "blocklisted", "requestable_seasons": []}
    if has_media and not {"seasons", "requests"} <= set(info):
        return {"reason": "unverified_season_status", "requestable_seasons": []}
    state_rows = info.get("seasons", [])
    requests = info.get("requests", [])
    if not isinstance(state_rows, list) or not isinstance(requests, list):
        return {"reason": "unverified_season_status", "requestable_seasons": []}
    states = {}
    for row in state_rows:
        if not isinstance(row, dict) or type(row.get("seasonNumber")) is not int:
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        number = row["seasonNumber"]
        if number in states and states[number] != row.get("status"):
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        if type(row.get("status")) is not int or row["status"] not in range(1, 8):
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        states[number] = row["status"]
    held = set()
    for request in requests:
        if not isinstance(request, dict):
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        if "is4k" in request and type(request["is4k"]) is not bool:
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        if request.get("is4k") is True or request.get("status") in (3, 5):
            continue
        if (
            request.get("status") not in (1, 2, 4)
            or not isinstance(request.get("seasons"), list)
            or not request["seasons"]
        ):
            return {"reason": "unverified_season_status", "requestable_seasons": []}
        for row in request["seasons"]:
            if not isinstance(row, dict) or type(row.get("seasonNumber")) is not int:
                return {"reason": "unverified_season_status", "requestable_seasons": []}
            held.add(row["seasonNumber"])
    available, requested, progressing, blocked, missing, unknown = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    for number in seasons:
        status = states.get(number)
        if status == 5:
            available.append(number)
        elif number in held:
            requested.append(number)
        elif status in (2, 3, 4):
            progressing.append(number)
        elif status == 6:
            blocked.append(number)
        elif status in (1, 7) or (number not in states and info.get("status") != 5):
            missing.append(number)
        else:
            unknown.append(number)
    reason = None
    if unknown:
        reason = "unverified_season_status"
    elif blocked:
        reason = "blocklisted"
    elif not missing:
        reason = (
            "already_available"
            if len(available) == len(seasons)
            else "already_requested"
            if requested and not progressing
            else "already_in_progress"
        )
    return {
        "reason": reason,
        "requested_seasons": seasons,
        "requestable_seasons": missing,
        "available_seasons": available,
        "already_requested_seasons": requested,
        "in_progress_seasons": progressing,
        "blocked_seasons": blocked,
        "unverified_seasons": unknown,
    }


def _identity_matches(details, media):
    if (
        not isinstance(details, dict)
        or type(details.get("id")) is not int
        or not isinstance(details.get("name"), str)
        or not isinstance(details.get("firstAirDate", ""), (str, type(None)))
    ):
        return False
    return (
        details.get("id") == media["id"]
        and normalize_title(details.get("name") or "")
        == normalize_title(media.get("name") or "")
        and (details.get("firstAirDate") or "")[:4]
        == (media.get("firstAirDate") or "")[:4]
    )


def _pause(
    title,
    inspection,
    storage,
    stage,
    *,
    year=None,
    media_id=None,
    seasons=None,
    all_seasons=False,
    reason=None,
):
    if storage is None:
        return _outcome(
            reason
            or (
                "no_unique_match"
                if stage == "select_show"
                else "season_selection_required"
            ),
            inspection,
        )
    candidates = inspection.get("candidates")
    if candidates is None:
        media = inspection["media"]
        candidates = [
            {
                "title": media["name"],
                "year": (media.get("firstAirDate") or "")[:4],
                "media_type": "tv",
                "media_id": media["id"],
            }
        ]
    identifier = storage.create_continuation(
        title,
        candidates,
        context={
            "media_type": "tv",
            "stage": stage,
            "year": year,
            "media_id": media_id,
            "seasons": seasons,
            "all_seasons": all_seasons,
            "season_catalog": inspection.get("season_catalog", []),
        },
    )
    return _outcome(
        reason
        or (
            "no_unique_match" if stage == "select_show" else "season_selection_required"
        ),
        inspection,
        continuation_id=identifier,
    )


def prepare_tv_request(
    title: str,
    year=None,
    *,
    seasons=None,
    all_seasons=False,
    storage: SeerrRequestStorage | None = None,
    expected_media_id=None,
):
    """Prepare a TV request without guessing season scope or show identity."""
    seasons = validate_seasons(seasons, all_seasons)
    match = re.fullmatch(r"(.+?)\s+\(((?:18|19|20|21)\d{2})\)", title.strip())
    if match:
        if year is not None and year != int(match[2]):
            return _outcome("conflicting_year")
        title, year = match[1], int(match[2])
    resolution = find_media(title, media_type="tv", year=year)
    if not resolution["resolved"]:
        if (
            resolution["reason"] == "no_unique_match"
            and len(resolution.get("candidates", [])) > 1
        ):
            return _pause(
                title,
                resolution,
                storage,
                "select_show",
                year=year,
                seasons=seasons,
                all_seasons=all_seasons,
            )
        return _outcome(resolution["reason"], resolution)
    media = resolution["media"]
    if media.get("mediaType") != "tv" or (
        expected_media_id is not None and media["id"] != expected_media_id
    ):
        return _outcome("media_identity_changed", resolution)
    details = get_media_details("tv", media["id"])
    if not _identity_matches(details, media):
        return _outcome("media_identity_changed", resolution)
    catalog = _catalog(details)
    inspection = {**resolution, "season_catalog": list((catalog or {}).values())}
    if catalog is None:
        return _outcome("invalid_season_catalog", inspection)
    if not catalog:
        return _outcome("no_seasons_available", inspection)
    selected_year = (
        int(media["firstAirDate"][:4])
        if (media.get("firstAirDate") or "")[:4].isdigit()
        else year
    )
    if seasons is None and not all_seasons:
        return _pause(
            title,
            inspection,
            storage,
            "select_seasons",
            year=selected_year,
            media_id=media["id"],
        )
    if all_seasons:
        seasons = sorted(
            [
                number
                for number, item in catalog.items()
                if number > 0
                and type(item["episode_count"]) is int
                and item["episode_count"] > 0
            ]
        )
        if not seasons:
            return _outcome("no_regular_seasons_available", inspection)
        if len(seasons) > 100:
            return _pause(
                title,
                inspection,
                storage,
                "select_seasons",
                year=selected_year,
                media_id=media["id"],
                reason="invalid_season_selection",
            )
    plan = evaluate_tv_seasons(details, seasons)
    if plan["reason"] == "invalid_season_selection":
        return _pause(
            title,
            inspection,
            storage,
            "select_seasons",
            year=selected_year,
            media_id=media["id"],
            reason="invalid_season_selection",
        )
    outcome = _outcome(
        plan["reason"],
        inspection,
        **{key: value for key, value in plan.items() if key != "reason"},
        title=media["name"],
        media_id=media["id"],
    )
    if plan["reason"]:
        return outcome
    authorized = request_authorized(
        explicit_acquisition_intent=True,
        unambiguous_match=True,
        already_available=False,
        already_requested=False,
    )
    outcome["authorized"] = authorized
    outcome["reason"] = None if authorized else "auto_request_disabled"
    outcome["submission"] = (
        {"submitted": False, "reason": "dry_run"}
        if not authorized
        else submit_tv_request(media, plan["requestable_seasons"])
    )
    return outcome


def submit_tv_request(media, seasons):
    """Recheck selected seasons and policy immediately before one non-retried POST."""
    details = get_media_details("tv", media["id"])
    if not _identity_matches(details, media):
        return {"submitted": False, "reason": "media_identity_changed"}
    plan = evaluate_tv_seasons(details, seasons)
    if plan["reason"]:
        return {"submitted": False, "reason": plan["reason"]}
    if not request_authorized(
        explicit_acquisition_intent=True,
        unambiguous_match=True,
        already_available=False,
        already_requested=False,
    ):
        return {"submitted": False, "reason": "dry_run"}
    selected = plan["requestable_seasons"]
    try:
        response = request_tv(media["id"], selected)
    except RuntimeError:
        return {"submitted": None, "reason": "submission_uncertain"}
    request_id = response.get("id") if isinstance(response, dict) else None
    returned = response.get("seasons") if isinstance(response, dict) else None
    if type(request_id) is not int or request_id <= 0 or not isinstance(returned, list):
        return {"submitted": None, "reason": "submission_uncertain"}
    numbers = [
        item.get("seasonNumber") if isinstance(item, dict) else None
        for item in returned
    ]
    if not numbers or any(
        type(number) is not int or number not in selected for number in numbers
    ):
        return {
            "submitted": None,
            "reason": "submission_uncertain",
            "request_id": request_id,
        }
    return {
        "submitted": True,
        "request_id": request_id,
        "seasons": sorted(set(numbers)),
    }


def _season_reply(question):
    question = question.strip().lower().rstrip(".!?")
    if question in {"all", "all seasons", "the whole series", "whole series"}:
        return None, True
    text = re.sub(r"^(?:seasons?\s*|s(?=\d))", "", question)
    if not re.fullmatch(r"\d{1,3}(?:(?:\s*(?:,|and|-)\s*|\s+)\d{1,3})*", text):
        return None, False
    if "-" in text:
        match = re.fullmatch(r"(\d{1,3})\s*-\s*(\d{1,3})", text)
        if not match or not 0 <= int(match[2]) - int(match[1]) < 100:
            return None, False
        return list(range(int(match[1]), int(match[2]) + 1)), False
    return sorted(set(int(number) for number in re.findall(r"\d+", text))), False


def continue_tv_request(
    identifier, question, *, year=None, seasons=None, all_seasons=False, storage
):
    """Use typed single-use state to continue show/year or season clarification."""
    seasons = validate_seasons(seasons, all_seasons)
    record = storage.get_continuation(identifier)
    if record is None or record.get("context", {}).get("media_type") != "tv":
        raise TVContinuationError("Invalid or expired TV continuation")
    context = record["context"]
    candidates = record["candidates"]
    media_id = context.get("media_id")
    if context["stage"] == "select_show":
        if year is None:
            reply = question.strip().lower()
            if reply in {"the new one", "new one", "the newest", "newest", "latest"}:
                years = [
                    int(item["year"])
                    for item in candidates
                    if str(item.get("year", "")).isdigit()
                ]
                year = max(years) if years else None
            else:
                match = re.fullmatch(
                    r"(?:the )?((?:18|19|20|21)\d{2})(?: version)?", reply
                )
                year = int(match[1]) if match else None
        choices = [item for item in candidates if str(item.get("year")) == str(year)]
        if year is None or len(choices) != 1:
            return _outcome(
                "show_selection_required",
                {"candidates": candidates},
                continuation_id=identifier,
            )
        media_id = choices[0]["media_id"]
        if seasons is None and not all_seasons:
            seasons, all_seasons = (
                context.get("seasons"),
                context.get("all_seasons", False),
            )
    else:
        if year is not None and year != context.get("year"):
            return _outcome("show_identity_locked", continuation_id=identifier)
        year = context.get("year")
        if seasons is None and not all_seasons:
            seasons, all_seasons = _season_reply(question)
        if seasons is None and not all_seasons:
            return _outcome(
                "season_selection_required",
                {
                    "media": {
                        "id": media_id,
                        "name": record["title"],
                        "firstAirDate": f"{year}-01-01" if year else "",
                    },
                    "season_catalog": context.get("season_catalog", []),
                },
                continuation_id=identifier,
            )
    if storage.consume_continuation(identifier) is None:
        raise TVContinuationError("TV continuation already consumed")
    return prepare_tv_request(
        record["title"],
        year,
        seasons=seasons,
        all_seasons=all_seasons,
        storage=storage,
        expected_media_id=media_id,
    )


def tv_result(outcome):
    """Render an honest season-specific answer without a reasoning-model call."""
    reason = outcome.get("reason")
    inspection = outcome.get("inspection", {})
    media = inspection.get("media") or {}
    title = media.get("name") or outcome.get("title") or "TV show"
    year = (media.get("firstAirDate") or "")[:4]
    name = f"{title} ({year})" if year else title
    if (
        "submitted" in outcome.get("submission", {})
        and outcome["submission"]["submitted"] is None
    ):
        answer = (
            f"{name}: submission outcome is uncertain. Check Seerr before retrying."
        )
    elif reason in ("no_unique_match", "show_selection_required") and outcome.get(
        "continuation_id"
    ):
        choices = ", ".join(
            f"{item['title']} ({item.get('year') or 'unknown year'} TV series)"
            for item in inspection.get("candidates", [])
        )
        answer = f"Which TV series: {choices}? No request was submitted."
    elif reason in ("season_selection_required", "invalid_season_selection"):
        regular = [
            item["season"]
            for item in inspection.get("season_catalog", [])
            if item["season"] > 0
        ]
        answer = (
            f"{name}: which seasons would you like? Provide season numbers or say 'all seasons'. "
            f"Regular seasons listed: {regular}. Specials require explicit season 0. No request was submitted."
        )
    else:
        submission = outcome.get("submission", {})
        if submission.get("submitted") is True:
            answer = f"Requested {name}, seasons {submission['seasons']}."
        else:
            explanations = {
                "auto_request_disabled": "automatic acquisition is disabled",
                "already_available": "selected seasons are already available",
                "already_requested": "selected seasons are already available or requested",
                "already_in_progress": "selected seasons are already available or in progress",
                "search_too_broad": "search could not be completed",
                "no_unique_match": "no unique matching TV series",
                "unverified_season_status": "season status could not be verified",
                "season_has_no_episodes": "a selected season has no listed episodes",
                "invalid_season_catalog": "season information could not be verified",
                "no_seasons_available": "no seasons are listed for this series",
                "no_regular_seasons_available": "no regular seasons with listed episodes are available to select",
                "show_identity_locked": "this continuation belongs to the previously selected TV series",
                "media_identity_changed": "series identity changed; start a new search",
                "blocklisted": "the series or selected season is blocklisted",
            }
            explanations["dry_run"] = "automatic acquisition is disabled"
            reason = submission.get("reason") if not reason else reason
            description = explanations.get(reason, reason or "not requestable")
            answer = f"{name}: {description}. No request was submitted."
        summary = {
            key: outcome[key]
            for key in (
                "requested_seasons",
                "requestable_seasons",
                "available_seasons",
                "already_requested_seasons",
                "in_progress_seasons",
            )
            if outcome.get(key)
        }
        labels = {
            "requested_seasons": "selected",
            "requestable_seasons": "missing",
            "available_seasons": "available",
            "already_requested_seasons": "already requested",
            "in_progress_seasons": "in progress",
        }
        if summary:
            answer += (
                " Season summary: "
                + "; ".join(f"{labels[key]}: {value}" for key, value in summary.items())
                + "."
            )
    return acquisition_response(
        {
            "answer": answer,
            "completed": True,
            "tool_calls": 0,
            "observations": [outcome],
            "continuation_id": outcome.get("continuation_id"),
        },
        outcome,
    )
