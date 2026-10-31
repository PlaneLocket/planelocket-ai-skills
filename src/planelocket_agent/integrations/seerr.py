"""Seerr media discovery and request integration."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
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


def _seerr_get(endpoint: str, params: dict | None = None, *, timeout: float = 10):
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
        with opener.open(request, timeout=timeout) as response:
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


SEARCH_MAX_RESULTS = 2000
SEARCH_MAX_PAGES = 100
SEARCH_WORKERS = 6
SEARCH_BUDGET_SECONDS = 40


def search_media(query: str) -> dict:
    """Collect a complete bounded search before allowing identity resolution.

    Fetch small batches concurrently so common short titles do not require
    dozens of serial round trips. Never present a partial page set as complete.
    """
    query = query.strip()
    if not query:
        raise ValueError("Search query cannot be empty")

    deadline = time.monotonic() + SEARCH_BUDGET_SECONDS
    total_results = None
    total_pages = None

    def incomplete(reason):
        return {
            "results": [],
            "total_results": total_results,
            "total_pages": total_pages,
            "complete": False,
            "incomplete_reason": reason,
        }

    def fetch(page):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Search budget exhausted")
        return _seerr_get(
            "search", {"query": query, "page": page}, timeout=min(10, remaining)
        )

    try:
        first = fetch(1)
    except RuntimeError, TimeoutError:
        return incomplete("search_failed")
    if not isinstance(first, dict):
        return incomplete("invalid_pagination")
    total_results = first.get("totalResults")
    total_pages = first.get("totalPages")
    if (
        type(total_results) is not int
        or total_results < 0
        or type(total_pages) is not int
        or total_pages < 1
    ):
        return incomplete("invalid_pagination")
    if total_results > SEARCH_MAX_RESULTS or total_pages > SEARCH_MAX_PAGES:
        return incomplete("search_limit")

    def valid_page(response, page):
        return (
            isinstance(response, dict)
            and type(response.get("page")) is int
            and response["page"] == page
            and response.get("totalResults") == total_results
            and response.get("totalPages") == total_pages
            and isinstance(response.get("results"), list)
            and all(isinstance(item, dict) for item in response["results"])
        )

    if not valid_page(first, 1):
        return incomplete("invalid_pagination")
    results = list(first["results"])
    # Submit only one batch at a time. When the budget expires there is no
    # backlog of queued requests continuing to hit Seerr after returning.
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as pool:
        for start in range(2, total_pages + 1, SEARCH_WORKERS):
            if time.monotonic() >= deadline:
                return incomplete("search_timeout")
            pages = range(start, min(start + SEARCH_WORKERS, total_pages + 1))
            try:
                responses = list(pool.map(fetch, pages))
            except RuntimeError, TimeoutError:
                return incomplete("page_failed")
            for page, response in zip(pages, responses):
                if not valid_page(response, page):
                    return incomplete("pagination_changed")
                results.extend(response["results"])
            if len(results) > SEARCH_MAX_RESULTS:
                return incomplete("search_limit")

    if time.monotonic() >= deadline:
        return incomplete("search_timeout")
    if len(results) != total_results:
        return incomplete("result_count_mismatch")
    unique = {}
    identity_fields = (
        "title",
        "name",
        "originalTitle",
        "originalName",
        "releaseDate",
        "firstAirDate",
    )
    for item in results:
        kind, identifier = item.get("mediaType"), item.get("id")
        if not isinstance(kind, str) or type(identifier) is not int or identifier <= 0:
            return incomplete("invalid_identity")
        key = (kind, identifier)
        if key in unique:
            # Repeated appearances of one upstream media object are not
            # separate candidates. Conflicting identity data is still unsafe.
            if any(
                unique[key].get(field) != item.get(field) for field in identity_fields
            ):
                return incomplete("conflicting_identity")
        else:
            unique[key] = item
    return {
        "results": list(unique.values()),
        "total_results": total_results,
        "unique_results": len(unique),
        "duplicates_omitted": len(results) - len(unique),
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


def request_tv(media_id: int, seasons: list[int]) -> dict:
    """Submit explicitly selected TV seasons; callers enforce authorization."""
    if type(media_id) is not int or media_id <= 0:
        raise ValueError("media_id must be a positive integer")
    if (
        not isinstance(seasons, list)
        or not 1 <= len(seasons) <= 100
        or any(type(number) is not int or not 0 <= number <= 999 for number in seasons)
        or len(set(seasons)) != len(seasons)
    ):
        raise ValueError("seasons must be distinct nonnegative integers")
    return _seerr_post(
        "request",
        {
            "mediaType": "tv",
            "mediaId": media_id,
            "seasons": sorted(seasons),
            "is4k": False,
        },
    )
