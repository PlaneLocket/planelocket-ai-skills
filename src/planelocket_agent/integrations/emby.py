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


def get_artist_tracks(artist_id: str) -> list[dict]:
    """Return audio tracks associated with an Emby music artist."""
    data = _emby_get(
        "Items",
        {
            "IncludeItemTypes": "Audio",
            "ArtistIds": artist_id,
            "Recursive": "true",
        },
    )

    return [
        {
            "name": item.get("Name"),
            "artists": item.get("Artists", []),
            "album": item.get("Album"),
            "id": item.get("Id"),
        }
        for item in data.get("Items", [])
    ]


def search_artists(name: str) -> list[dict]:
    """Search the Emby music library for artists matching a name."""
    data = _emby_get(
        "Artists",
        {
            "SearchTerm": name,
            "Fields": "SortName",
        },
    )

    return [
        {
            "name": artist.get("Name"),
            "sort_name": artist.get("SortName"),
            "id": artist.get("Id"),
        }
        for artist in data.get("Items", [])
    ]


def get_artist_albums(artist_id: str) -> list[dict]:
    """Return music albums associated with an Emby artist."""
    data = _emby_get(
        "Items",
        {
            "IncludeItemTypes": "MusicAlbum",
            "ArtistIds": artist_id,
            "Recursive": "true",
            "Fields": "ProductionYear",
        },
    )

    return [
        {
            "name": album.get("Name"),
            "artist": album.get("AlbumArtist"),
            "year": album.get("ProductionYear"),
            "id": album.get("Id"),
        }
        for album in data.get("Items", [])
    ]


def get_album_tracks(album_id: str) -> list[dict]:
    """Return audio tracks belonging to an Emby music album."""
    data = _emby_get(
        "Items",
        {
            "IncludeItemTypes": "Audio",
            "ParentId": album_id,
            "Recursive": "true",
        },
    )

    return [
        {
            "name": track.get("Name"),
            "artists": track.get("Artists", []),
            "track_number": track.get("IndexNumber"),
            "disc_number": track.get("ParentIndexNumber"),
            "id": track.get("Id"),
        }
        for track in data.get("Items", [])
    ]


def search_people(name: str) -> list[dict]:
    """Search Emby for people matching a name."""
    data = _emby_get(
        "Persons",
        {
            "SearchTerm": name,
            "Limit": 25,
        },
    )

    return [
        {
            "name": person.get("Name"),
            "id": person.get("Id"),
        }
        for person in data.get("Items", [])
    ]


def get_person_movies(person_id: str) -> list[dict]:
    """Return all library movies associated with an Emby person."""
    movies = []
    start_index = 0
    page_size = 100

    while True:
        data = _emby_get(
            "Items",
            {
                "PersonIds": person_id,
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "Fields": "ProductionYear",
                "StartIndex": start_index,
                "Limit": page_size,
            },
        )

        items = data.get("Items", [])

        movies.extend(
            {
                "name": movie.get("Name"),
                "year": movie.get("ProductionYear"),
                "id": movie.get("Id"),
            }
            for movie in items
        )

        start_index += len(items)

        if not items:
            break

        total = data.get("TotalRecordCount")

        if total is not None and start_index >= total:
            break

        if total is None and len(items) < page_size:
            break

    return movies
