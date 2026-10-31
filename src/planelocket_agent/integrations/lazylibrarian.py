"""Narrow LazyLibrarian a0fe7646 API adapter; no caller-supplied commands/URLs."""

import argparse
import hashlib
import json
import os
import re
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from planelocket_agent.integrations.calibre_web import (
    BookError,
    _RejectRedirects,
    normalize_origin,
    text,
)

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_BOOKS = 10000
SOURCES = {"OpenLibrary", "GoogleBooks", "HardCover", "GoodReads"}
CONFIG_NAMES = {
    "BOOK_API": "API",
    "NEWAUDIO_STATUS": "LibraryScan",
    "NEWBOOK_STATUS": "LibraryScan",
}


def book_id(value):
    if type(value) is int and value > 0:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise BookError("ll_invalid_response")
    return value


def auto_request_enabled():
    return (
        os.environ.get("LAZYLIBRARIAN_AUTO_REQUEST", "false").strip().lower() == "true"
    )


class LazyLibrarianClient:
    def __init__(self, url, api_key):
        try:
            self._url = normalize_origin(url)
        except BookError:
            raise BookError("ll_not_configured") from None
        if not isinstance(api_key, str) or not re.fullmatch(
            r"[A-Za-z0-9]{32}", api_key
        ):
            raise BookError("ll_not_configured")
        self._key = api_key
        self._opener = build_opener(_RejectRedirects())
        self._lock = threading.RLock()
        self._depth = 0
        # Replaced keys invalidate pending choices; never expose the key itself.
        self.target = hashlib.sha256(
            json.dumps(["lazylibrarian", self._url, api_key]).encode()
        ).hexdigest()

    @contextmanager
    def session(self):
        with self._lock:
            if self._depth == 0:
                self._deadline = time.monotonic() + 60
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1

    def safe_text(self, value, maximum=500, *, optional=False):
        if optional and value in (None, ""):
            return None
        if type(value) is int:
            value = str(value)
        try:
            return text(value, maximum).replace(self._key, "[REDACTED]")
        except BookError:
            raise BookError("ll_invalid_response") from None

    def _call(self, command, **params):
        allowed = {
            "getVersion": set(),
            "getAllBooks": {"limit"},
            "findBook": {"name"},
            "readCFG": {"name", "group"},
            "addBook": {"id", "source", "wait"},
            "queueBook": {"id", "type"},
            "searchBook": {"id", "type"},
        }
        if command not in allowed or set(params) != allowed[command]:
            raise BookError("invalid_arguments")
        if command == "readCFG" and CONFIG_NAMES.get(params["name"]) != params["group"]:
            raise BookError("invalid_arguments")
        if command in {"addBook", "queueBook", "searchBook"}:
            params["id"] = book_id(params["id"])
        if command in {"queueBook", "searchBook"} and params["type"] != "eBook":
            raise BookError("invalid_arguments")
        if command == "addBook" and (
            params["source"] not in SOURCES or params["wait"] != "1"
        ):
            raise BookError("invalid_arguments")
        if command == "getAllBooks" and params["limit"] != MAX_BOOKS + 1:
            raise BookError("invalid_arguments")
        mutation = command in {"addBook", "queueBook", "searchBook"}
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise BookError("ll_timeout")
        # CherryPy accepts form fields in POST. Keep the API key out of URL/logs.
        request = Request(
            self._url + "/api",
            data=urlencode({"apikey": self._key, "cmd": command, **params}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/plain",
            },
        )
        try:
            with self._opener.open(request, timeout=min(30, remaining)) as response:
                if response.status != 200:
                    raise BookError("ll_invalid_response", uncertain=mutation)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise BookError("ll_response_too_large", uncertain=mutation)
                value = raw.decode("utf-8").strip()
                if time.monotonic() >= self._deadline:
                    raise BookError("ll_timeout", uncertain=mutation)
                # LL returns JSON and plain tokens with a text/html content type.
                try:
                    result = json.loads(value)
                except ValueError:
                    result = value
                if isinstance(result, dict) and result.get("Success") is False:
                    code = (
                        (result.get("Error") or {}).get("Code")
                        if isinstance(result.get("Error"), dict)
                        else None
                    )
                    message = (
                        result["Error"].get("Message")
                        if isinstance(result.get("Error"), dict)
                        else None
                    )
                    failure = (
                        "ll_invalid_auth" if code == 401 else "ll_request_rejected"
                    )
                    if code == 405 and isinstance(message, str):
                        if message.startswith("Unknown command:"):
                            failure = "ll_unsupported_command"
                        elif "not available with read-only api access key" in message:
                            failure = "ll_forbidden"
                    raise BookError(failure)
                if command == "readCFG":
                    if not isinstance(result, str) or not re.fullmatch(
                        r"\[[A-Za-z]{1,30}\]", result
                    ):
                        raise BookError("ll_invalid_response")
                    value = result[1:-1]
                    if params["name"] == "BOOK_API" and value not in SOURCES:
                        raise BookError("ll_invalid_response")
                    return value
                if (
                    command == "searchBook"
                    and result == "No search methods set, check config"
                ):
                    raise BookError("ll_search_not_configured")
                if command in {"queueBook", "searchBook"} and result != "OK":
                    raise BookError("ll_invalid_response", uncertain=True)
                if command == "addBook" and result is not True:
                    # Metadata import may have side effects before returning failure.
                    raise BookError("ll_add_unverified", uncertain=True)
                if command == "getVersion" and not isinstance(result, dict):
                    raise BookError("ll_invalid_response")
                if command in {"findBook", "getAllBooks"} and not isinstance(
                    result, list
                ):
                    raise BookError("ll_invalid_response")
                return result
        except HTTPError as exc:
            code = (
                "ll_invalid_auth"
                if exc.code in (401, 403)
                else "ll_service_unavailable"
            )
            if 300 <= exc.code < 400:
                code = "ll_redirect_refused"
            uncertain = mutation and exc.code not in (400, 401, 403, 404, 405, 422, 429)
            exc.close()
            raise BookError(code, uncertain=uncertain) from None
        except TimeoutError:
            raise BookError("ll_timeout", uncertain=mutation) from None
        except URLError as exc:
            code = (
                "ll_timeout"
                if isinstance(exc.reason, TimeoutError)
                else "ll_cannot_connect"
            )
            raise BookError(code, uncertain=mutation) from None
        except OSError:
            raise BookError("ll_cannot_connect", uncertain=mutation) from None
        except UnicodeError, ValueError, RecursionError:
            raise BookError("ll_invalid_response", uncertain=mutation) from None

    def config(self, name):
        with self.session():
            if name not in CONFIG_NAMES:
                raise BookError("invalid_arguments")
            return self._call("readCFG", name=name, group=CONFIG_NAMES[name])

    def inventory(self):
        with self.session():
            data = self._call("getAllBooks", limit=MAX_BOOKS + 1)
            if len(data) > MAX_BOOKS:
                raise BookError("ll_incomplete_inventory")
            items, seen = [], set()
            for raw in data:
                item = self.item(raw)
                if item["book_id"] in seen:
                    raise BookError("ll_incomplete_inventory")
                seen.add(item["book_id"])
                items.append(item)
            return items

    def item(self, raw, *, external=False):
        if not isinstance(raw, dict):
            raise BookError("ll_invalid_response")
        raw = {k.lower(): v for k, v in raw.items()}
        source = raw.get("source") if external else "LazyLibrarian"
        if external and (not isinstance(source, str) or source not in SOURCES):
            raise BookError("ll_invalid_response")
        identifier = book_id(raw.get("bookid"))
        if self._key in identifier:
            raise BookError("ll_invalid_response")
        item = {
            "book_id": identifier,
            "title": self.safe_text(raw.get("bookname"), 1000),
            "authors": [self.safe_text(raw.get("authorname"), 300)],
            "year": self.safe_text(raw.get("bookdate"), 200, optional=True),
            "isbn": self.safe_text(raw.get("bookisbn"), 100, optional=True),
            "language": self.safe_text(raw.get("booklang"), 100, optional=True),
            "source": source,
        }
        if not external:
            item["status"] = self.safe_text(raw.get("status"), 30)
        return item

    def find(self, title):
        with self.session():
            data = self._call("findBook", name=text(title))
            if len(data) > 2000:
                raise BookError("ll_search_too_broad")
            # External search results are suggestions, not evidence of library absence.
            # Reject each unusable suggestion without discarding other valid choices.
            items, skipped = [], 0
            for raw in data:
                try:
                    items.append(self.item(raw, external=True))
                except BookError:
                    skipped += 1
            return {
                "items": items,
                "records_received": len(data),
                "records_skipped": skipped,
            }

    def add(self, identifier, source):
        with self.session():
            return self._call("addBook", id=identifier, source=source, wait="1")

    def queue(self, identifier):
        with self.session():
            return self._call("queueBook", id=identifier, type="eBook")

    def search(self, identifier):
        """Request one ebook's background search, without a bulk/wait command."""
        with self.session():
            return self._call("searchBook", id=identifier, type="eBook")

    def status(self, identifier):
        # getBook has a Python implementation upstream but is not registered in
        # a0fe7646's API command table. Use the supported inventory command.
        identifier = book_id(identifier)
        with self.session():
            row = next(
                (item for item in self.inventory() if item["book_id"] == identifier),
                None,
            )
            if row is None:
                raise BookError("ll_identity_changed")
            return {key: row[key] for key in ("title", "authors", "status")}


@lru_cache(maxsize=2)
def _cached_client(url, key):
    return LazyLibrarianClient(url, key)


def get_client():
    url, key = (
        os.environ.get(name) for name in ("LAZYLIBRARIAN_URL", "LAZYLIBRARIAN_API_KEY")
    )
    if not url or not key:
        raise BookError("ll_not_configured")
    return _cached_client(url, key)


def main():
    parser = argparse.ArgumentParser(description="Read-only LazyLibrarian API check")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    from planelocket_agent.config import load_config

    load_config()
    try:
        client = get_client()
        with client.session():
            version = client._call("getVersion")
            result = {
                "api_access": version.get("Success") is True,
                "current_version": client.safe_text(version.get("current_version"), 80),
                "metadata_source": client.config("BOOK_API"),
                "new_ebook_status": client.config("NEWBOOK_STATUS"),
                "new_audiobook_status": client.config("NEWAUDIO_STATUS"),
                "book_auto_request": auto_request_enabled(),
            }
            try:
                result.update(
                    inventory_access=True, inventory_records=len(client.inventory())
                )
            except BookError as exc:
                result.update(inventory_access=False, inventory_code=exc.code)
        print(json.dumps(result))
    except BookError as exc:
        print(json.dumps({"ok": False, "code": exc.code}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
