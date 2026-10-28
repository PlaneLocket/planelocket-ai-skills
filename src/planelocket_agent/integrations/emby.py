"""Communicate with the Emby media server."""

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def search_movies(title: str) -> list[dict]:
    """Search the Emby library for movies matching a title."""
    emby_url = os.environ.get("EMBY_URL")
    api_key = os.environ.get("EMBY_API_KEY")

    if not emby_url:
        raise ValueError("EMBY_URL is not configured")
    if not api_key:
        raise ValueError("EMBY_API_KEY is not configured")

    params = {
        "SearchTerm": title,
        "IncludeItemTypes": "Movie",
        "Recursive": "true",
        "Fields": "ProductionYear",
    }

    query = urlencode(params)

    url = f"{emby_url}/emby/Items?{query}"

    request = Request(
        url,
        headers={"X-Emby-Token": api_key},
    )

    with urlopen(request, timeout=10) as response:
        data = json.load(response)

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
