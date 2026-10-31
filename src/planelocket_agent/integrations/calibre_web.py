"""Bounded, session-authenticated Calibre-Web NextGen v4.1.52 JSON client."""

import argparse
import hashlib
import json
import os
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
    build_opener,
)

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LIBRARY_RESULTS = 500
OPERATION_SECONDS = 60


class BookError(Exception):
    """Sanitized error: never include remote bodies, credentials, or URLs."""

    def __init__(self, code, *, uncertain=False):
        self.code, self.uncertain = code, uncertain
        super().__init__(code)


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def text(value, maximum=500):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise BookError("invalid_arguments")
    return value.strip()


def normalize_origin(value):
    try:
        url = urlsplit(value)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError
        url.port
        return value.rstrip("/")
    except ValueError, TypeError, AttributeError:
        raise BookError("not_configured") from None


class CalibreWebClient:
    def __init__(self, url, username, password):
        self._url = normalize_origin(url)
        self._username = text(username, 200)
        if not isinstance(password, str) or not 1 <= len(password) <= 4096:
            raise BookError("not_configured")
        self._password = password
        self._cookies = CookieJar()
        self._opener = build_opener(
            HTTPCookieProcessor(self._cookies), _RejectRedirects()
        )
        self._lock = threading.RLock()
        self._depth = 0
        self._logged_in = False
        self._csrf = None
        self._user_id = None
        self.library_mode = None

    @property
    def target(self):
        material = [self._url, self._username.casefold(), self._user_id]
        return hashlib.sha256(json.dumps(material).encode()).hexdigest()

    def safe_text(self, value, maximum=500):
        try:
            value = text(value, maximum)
        except BookError:
            raise BookError("invalid_response") from None
        for secret in [
            self._password,
            self._csrf,
            *(cookie.value for cookie in self._cookies),
        ]:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value

    @contextmanager
    def session(self):
        with self._lock:
            if self._depth == 0:
                self._deadline = time.monotonic() + OPERATION_SECONDS
            self._depth += 1
            try:
                if not self._logged_in:
                    self._login()
                yield self
            finally:
                self._depth -= 1

    def _request(self, method, path, *, params=None, payload=None, expected=200):
        allowed = (
            method == "GET"
            and path
            in (
                "/health",
                "/auth/csrf",
                "/auth/me",
                "/books",
            )
        ) or (method == "POST" and path == "/auth/login")
        if not allowed:
            raise BookError("invalid_arguments")
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BookError("timeout")
        url = self._url + "/api/v1" + path
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
            if self._csrf:
                headers["X-CSRFToken"] = self._csrf
        try:
            req = Request(url, data=data, headers=headers, method=method)
            with self._opener.open(req, timeout=min(10, remaining)) as response:
                if response.status != expected:
                    raise BookError("invalid_response")
                if (
                    response.headers.get("Content-Type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                    != "application/json"
                ):
                    raise BookError("invalid_response")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise BookError("response_too_large")
                result = json.loads(body)
                if time.monotonic() >= self._deadline:
                    raise BookError("timeout")
                return result
        except HTTPError as exc:
            codes = {
                400: "request_rejected",
                401: "invalid_auth",
                403: "forbidden",
                404: "not_available",
                409: "request_rejected",
                422: "request_rejected",
                429: "rate_limited",
                301: "redirect_refused",
                302: "redirect_refused",
                303: "redirect_refused",
                307: "redirect_refused",
                308: "redirect_refused",
            }
            code = codes.get(exc.code, "service_unavailable")
            exc.close()
            raise BookError(code) from None
        except TimeoutError, URLError, OSError:
            raise BookError("cannot_connect") from None
        except ValueError, UnicodeError, RecursionError:
            raise BookError("invalid_response") from None

    def _csrf_token(self):
        data = self._request("GET", "/auth/csrf")
        token = data.get("csrf_token") if isinstance(data, dict) else None
        if (
            not isinstance(token, str)
            or not 1 <= len(token) <= 4096
            or any(not 33 <= ord(character) <= 126 for character in token)
        ):
            raise BookError("invalid_response")
        self._csrf = token

    def _login(self):
        self._logged_in = False
        self._cookies.clear()
        self._csrf_token()
        data = self._request(
            "POST",
            "/auth/login",
            payload={
                "username": self._username,
                "password": self._password,
                "remember": False,
            },
        )
        if (
            not isinstance(data, dict)
            or type(data.get("id")) is not int
            or data["id"] <= 0
            or not isinstance(data.get("name"), str)
            or data["name"].strip().casefold() != self._username.casefold()
            or not list(self._cookies)
        ):
            raise BookError("invalid_auth")
        if self._user_id is not None and self._user_id != data["id"]:
            raise BookError("invalid_auth")
        self._user_id = data["id"]
        mode = data.get("library_mode")
        self.library_mode = (
            mode
            if isinstance(mode, str) and mode in {"monolibrary", "personal_library"}
            else None
        )
        self._logged_in = True

    def get(self, path, params=None):
        with self.session():
            try:
                return self._request("GET", path, params=params)
            except BookError as exc:
                if exc.code != "invalid_auth":
                    raise
                # Retry only a GET after reauthenticating. Never replay a job POST.
                self._login()
                return self._request("GET", path, params=params)

    def book_item(self, item):
        if (
            not isinstance(item, dict)
            or type(item.get("id")) is not int
            or not 0 < item["id"] < 2**63
            or not isinstance(item.get("authors"), list)
            or not isinstance(item.get("formats"), list)
        ):
            raise BookError("invalid_response")
        authors = [self.safe_text(value, 300) for value in item["authors"]]
        formats = [self.safe_text(value, 20).upper() for value in item["formats"]]
        series = item.get("series")
        if series is not None:
            series = self.safe_text(series)
        return {
            "id": item["id"],
            "title": self.safe_text(item.get("title"), 1000),
            "authors": authors,
            "formats": formats,
            "series": series,
        }

    def search_library(self, query):
        query = text(query)
        with self.session():
            rows, total = {}, None
            for page in range(1, MAX_LIBRARY_RESULTS // 50 + 1):
                result = self.get(
                    "/books", {"search": query, "page": page, "per_page": 50}
                )
                if (
                    not isinstance(result, dict)
                    or type(result.get("total")) is not int
                    or result["total"] < 0
                    or type(result.get("page")) is not int
                    or result.get("page") != page
                    or result.get("per_page") != 50
                    or not isinstance(result.get("items"), list)
                ):
                    raise BookError("invalid_response")
                if total is None:
                    total = result["total"]
                elif total != result["total"]:
                    return {
                        "items": list(rows.values()),
                        "total": total,
                        "complete": False,
                    }
                for item in result["items"]:
                    item = self.book_item(item)
                    if item["id"] in rows:
                        return {
                            "items": list(rows.values()),
                            "total": total,
                            "complete": False,
                        }
                    rows[item["id"]] = item
                if len(rows) == total:
                    return {
                        "items": list(rows.values()),
                        "total": total,
                        "complete": True,
                    }
                if (
                    len(rows) > total
                    or not result["items"]
                    or total > MAX_LIBRARY_RESULTS
                ):
                    break
            return {"items": list(rows.values()), "total": total, "complete": False}


@lru_cache(maxsize=2)
def _cached_client(url, username, password):
    return CalibreWebClient(url, username, password)


def get_client():
    values = [
        os.environ.get(key) for key in ("CWNG_URL", "CWNG_USERNAME", "CWNG_PASSWORD")
    ]
    if any(value is None or value == "" for value in values):
        raise BookError("not_configured")
    return _cached_client(*values)


def main():
    parser = argparse.ArgumentParser(description="Read-only NextGen connection check")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    from planelocket_agent.config import load_config

    load_config()
    try:
        client = get_client()
        with client.session():
            library = client.get("/books", {"page": 1, "per_page": 1})
            if not isinstance(library, dict) or type(library.get("total")) is not int:
                raise BookError("invalid_response")
            result = {
                "library_access": True,
                "visible_books": library["total"],
                "library_mode": client.library_mode,
            }

        print(json.dumps(result))
    except BookError as exc:
        print(json.dumps({"ok": False, "code": exc.code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
