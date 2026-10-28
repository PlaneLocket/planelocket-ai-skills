"""Communicate with the Emby media server."""

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _emby_get(endpoint: str, params: dict | None = None) -> dict:
    """Make an authenticated GET request to Emby and return JSON data."""
    emby_url = os.environ.get("EMBY_URL")
    api_key = os.environ.get("EMBY_API_KEY")

    if not emby_url:
        raise ValueError("EMBY_URL is not configured")
    if not api_key:
        raise ValueError("EMBY_API_KEY is not configured")

    url = f"{emby_url.rstrip('/')}/emby/{endpoint.lstrip('/')}"

    if params:
        url = f"{url}?{urlencode(params)}"

    request = Request(
        url,
        headers={"X-Emby-Token": api_key},
    )

    with urlopen(request, timeout=10) as response:
        return json.load(response)


def search_movies(title: str) -> list[dict]:
    """Search the Emby library for movies matching a title."""
    data = _emby_get(
        "Items",
        {
            "SearchTerm": title,
            "IncludeItemTypes": "Movie",
            "Recursive": "true",
            "Fields": "ProductionYear",
        },
    )

    results = []

    for movie in data.get("Items", []):
        results.append(
            {
                "name": movie.get("Name"),
                "year": movie.get("ProductionYear"),
                "id": movie.get("Id"),
            }
        )

    return results


def search_series(title: str) -> list[dict]:
    """Search Emby for television series matching a title."""
    data = _emby_get(
        "Items",
        {
            "SearchTerm": title,
            "IncludeItemTypes": "Series",
            "Recursive": "true",
        },
    )

    return [
        {
            "name": item.get("Name"),
            "id": item.get("Id"),
        }
        for item in data.get("Items", [])
    ]


def get_seasons(series_id: str) -> list[dict]:
    """Return the available seasons for an Emby television series."""
    data = _emby_get(
        f"Shows/{series_id}/Seasons",
        {"SeriesId": series_id},
    )

    return [
        {
            "name": season.get("Name"),
            "number": season.get("IndexNumber"),
            "id": season.get("Id"),
        }
        for season in data.get("Items", [])
    ]


def get_episodes(series_id: str, season_id: str) -> list[dict]:
    """Return episodes belonging to a specific television season."""
    data = _emby_get(
        f"Shows/{series_id}/Episodes",
        {
            "SeriesId": series_id,
            "SeasonId": season_id,
        },
    )

    return [
        {
            "name": episode.get("Name"),
            "season": episode.get("ParentIndexNumber"),
            "episode": episode.get("IndexNumber"),
            "id": episode.get("Id"),
        }
        for episode in data.get("Items", [])
    ]
