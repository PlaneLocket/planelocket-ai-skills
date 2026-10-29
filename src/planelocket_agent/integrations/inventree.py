"""Read-only InvenTree inventory integration."""

import json
import os
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _RejectRedirects(HTTPRedirectHandler):
    """Prevent authenticated requests from following HTTP redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _origin(url: str) -> tuple[str, str, int]:
    """Return a URL's scheme, hostname, and effective port."""
    parsed = urlsplit(url)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("InvenTree URL must use HTTPS")

    return (
        parsed.scheme,
        parsed.hostname,
        parsed.port or 443,
    )


def _inventree_get(endpoint: str, params: dict | None = None):
    """Make authenticated, read-only InvenTree API requests.

    Supports both unpaginated lists and paginated DRF responses.
    """
    base_url = os.environ["INVENTREE_URL"].rstrip("/")
    token = os.environ["INVENTREE_API_TOKEN"]
    _origin(base_url)

    url = f"{base_url}/api/{endpoint.lstrip('/')}"

    if params:
        url += f"?{urlencode(params)}"

    headers = {"Authorization": f"Token {token}"}
    opener = build_opener(_RejectRedirects())
    results = []
    visited = set()
    redirects = 0

    while url:
        if url in visited:
            raise RuntimeError("InvenTree API pagination loop detected")

        visited.add(url)

        request = Request(url, headers=headers, method="GET")

        try:
            with opener.open(request, timeout=10) as response:
                data = json.load(response)

            redirects = 0

        except HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise

            location = exc.headers.get("Location")

            if not location:
                raise RuntimeError("InvenTree redirect has no Location header") from exc

            next_url = urljoin(url, location)

            if _origin(next_url) != _origin(base_url):
                raise RuntimeError(
                    "InvenTree redirect targets an untrusted origin"
                ) from exc

            redirects += 1

            if redirects > 5:
                raise RuntimeError(
                    "InvenTree exceeded the HTTP redirect limit"
                ) from exc

            url = next_url
            continue

        if isinstance(data, list):
            results.extend(data)
            break

        if isinstance(data, dict) and isinstance(data.get("results"), list):
            results.extend(data["results"])

            next_page = data.get("next")

            if next_page:
                next_url = urljoin(url, next_page)

                # Pagination must remain on the configured HTTPS origin.
                if _origin(next_url) != _origin(base_url):
                    raise RuntimeError(
                        "InvenTree pagination targets an untrusted origin"
                    )

                url = next_url
            else:
                url = None

            continue

        raise ValueError("Unexpected InvenTree API response format")

    return results


def search_parts(query: str):
    """Search InvenTree for matching parts."""
    return _inventree_get("part/", {"search": query})


def get_part_stock(part_id: int):
    """Retrieve stock records and actual locations for a part."""
    return _inventree_get(
        "stock/",
        {
            "part": part_id,
            "location_detail": "true",
        },
    )
