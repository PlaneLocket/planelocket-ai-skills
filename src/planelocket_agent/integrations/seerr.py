"""Seerr media discovery and request integration."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

MEDIA_STATUS = {
    1: "unknown",
    2: "pending",
    3: "processing",
    4: "partially_available",
    5: "available",
}


class _RejectRedirects(HTTPRedirectHandler):
    """Prevent authenticated requests from following HTTP redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _seerr_get(endpoint: str, params: dict | None = None):
    """Make an authenticated GET request to the Seerr API."""
    base_url = os.environ["SEERR_URL"].rstrip("/")
    api_key = os.environ["SEERR_API_KEY"]

    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"

    if params:
        url += f"?{urlencode(params, quote_via=quote)}"

    headers = {"X-Api-Key": api_key}
    request = Request(url, headers=headers, method="GET")
    opener = build_opener(_RejectRedirects())

    try:
        with opener.open(request, timeout=10) as response:
            data = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Seerr returned HTTP {exc.code}") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise RuntimeError("Seerr request timed out") from exc
        raise RuntimeError("Seerr couldn't be reached") from exc
    except TimeoutError as exc:
        raise RuntimeError("Seerr request timed out") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Seerr returned invalid JSON") from exc

    return data


def search_media(query: str) -> dict:
    """Search Seerr and retrieve all pages of matching media."""

    query = query.strip()

    if not query:
        raise ValueError("Search query cannot be empty")

    results = []
    page = 1
    total_pages = None

    while total_pages is None or page <= total_pages:
        response = _seerr_get(
            "search",
            {
                "query": query,
                "page": page,
            },
        )

        if total_pages is None:
            total_pages = response.get("totalPages")

            total_results = response.get("totalResults")

            if type(total_results) is not int or total_results < 0:
                raise RuntimeError("Invalid Seerr result count")

            if total_results > 200:
                return {
                    "results": [],
                    "total_results": total_results,
                    "total_pages": total_pages,
                    "complete": False,
                }

            if type(total_pages) is not int or total_pages < 1:
                raise RuntimeError("Invalid Seerr pagination information")

        page_results = response.get("results")

        if not isinstance(page_results, list):
            raise RuntimeError("Invalid Seerr search results")

        results.extend(page_results)
        page += 1

    return {
        "results": results,
        "total_results": len(results),
        "total_pages": total_pages,
        "complete": True,
    }


def get_media_details(media_type: str, media_id: int) -> dict:
    """Retrieve Seerr details and request status for a movie or TV series.

    media_id is the TMDB ID returned by search_media().
    This function performs no modifications.
    """
    if media_type not in ("movie", "tv"):
        raise ValueError("media_type must be 'movie' or 'tv'")

    if type(media_id) is not int or media_id <= 0:
        raise ValueError("media_id must be a positive integer")

    details = _seerr_get(f"{media_type}/{media_id}")

    media_info = details.get("mediaInfo") or {}

    details["availability"] = MEDIA_STATUS.get(
        media_info.get("status"),
        "unknown",
    )

    details["availability_4k"] = MEDIA_STATUS.get(
        media_info.get("status4k"),
        "unknown",
    )

    return details


def _seerr_post(endpoint: str, payload: dict) -> dict:
    """Submit an authenticated POST request to Seerr."""

    base_url = os.environ["SEERR_URL"].rstrip("/")
    api_key = os.environ["SEERR_API_KEY"]

    url = f"{base_url}/api/v1/{endpoint.lstrip('/')}"

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    opener = build_opener(_RejectRedirects())

    try:
        with opener.open(request, timeout=10) as response:
            return json.load(response)

    except HTTPError as exc:
        raise RuntimeError(f"Seerr request failed: HTTP {exc.code}") from exc

    except URLError as exc:
        raise RuntimeError("Seerr couldn't be reached") from exc

    except TimeoutError as exc:
        raise RuntimeError("Seerr request timed out") from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError("Seerr returned invalid JSON") from exc


def request_movie(media_id: int) -> dict:
    """Submit a movie acquisition request to Seerr.

    This function performs a write operation.
    Callers must enforce authorization before invoking it.
    """
    if type(media_id) is not int or media_id <= 0:
        raise ValueError("media_id must be a positive integer")

    return _seerr_post(
        "request",
        {
            "mediaType": "movie",
            "mediaId": media_id,
        },
    )
