"""Resolve Seerr search results to an unambiguous media item."""

import re
import unicodedata

from planelocket_agent.integrations.seerr import (
    get_media_details,
    search_media,
)


def normalize_title(title: str) -> str:
    """Normalize a title for exact matching."""

    title = unicodedata.normalize("NFKC", title)
    title = title.casefold()

    return re.sub(r"[\W_]+", " ", title).strip()


def resolve_media(
    results: list[dict],
    title: str,
    media_type: str | None = None,
    year: int | None = None,
) -> dict | None:
    """Return one exact match, or None when unresolved."""

    normalized_title = normalize_title(title)
    matches = []

    for item in results:
        if media_type and item.get("mediaType") != media_type:
            continue

        candidate_title = item.get("title") or item.get("name") or ""

        if normalize_title(candidate_title) != normalized_title:
            continue

        if year is not None:
            release_date = item.get("releaseDate") or item.get("firstAirDate") or ""

            if not release_date.startswith(f"{year}-"):
                continue

        matches.append(item)

    if len(matches) != 1:
        return None

    return matches[0]


def find_media(
    title: str,
    media_type: str | None = None,
    year: int | None = None,
) -> dict:
    """Find an unambiguous media item using complete Seerr results."""

    response = search_media(title)

    if not response["complete"]:
        return {
            "resolved": False,
            "reason": "search_too_broad",
            "media": None,
            "search": {
                key: response[key]
                for key in ("incomplete_reason", "total_results", "total_pages")
                if key in response
            },
        }

    match = resolve_media(
        response["results"],
        title=title,
        media_type=media_type,
        year=year,
    )

    if match is None:
        candidates = []

        for item in response["results"]:
            if media_type and item.get("mediaType") != media_type:
                continue

            candidate_title = item.get("title") or item.get("name") or ""

            if normalize_title(candidate_title) != normalize_title(title):
                continue

            release_date = item.get("releaseDate") or item.get("firstAirDate") or ""

            candidates.append(
                {
                    "title": candidate_title,
                    "year": release_date[:4] if release_date else None,
                    "media_type": item.get("mediaType"),
                    "media_id": item.get("id"),
                }
            )

        return {
            "resolved": False,
            "reason": "no_unique_match",
            "media": None,
            "candidates": candidates,
        }

    return {
        "resolved": True,
        "reason": None,
        "media": match,
    }


def inspect_media(
    title: str,
    media_type: str | None = None,
    year: int | None = None,
) -> dict:
    """Resolve a title and inspect its current Seerr availability."""

    resolution = find_media(
        title=title,
        media_type=media_type,
        year=year,
    )

    if not resolution["resolved"]:
        return resolution

    media = resolution["media"]

    details = get_media_details(
        media_type=media["mediaType"],
        media_id=media["id"],
    )

    return {
        "resolved": True,
        "reason": None,
        "media": media,
        "availability": details["availability"],
        "availability_4k": details["availability_4k"],
        "requests": (details.get("mediaInfo") or {}).get("requests", []),
    }
