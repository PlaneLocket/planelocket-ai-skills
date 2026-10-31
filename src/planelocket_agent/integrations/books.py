"""HAL book lookup and explicitly selected NextGen acquisition offers."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime

from planelocket_agent.integrations.calibre_web import (
    BookError,
    auto_request_enabled,
    get_client,
    opaque,
    text,
)

MAX_CHOICES = 20
FORMATS = {"EPUB", "PDF", "MOBI"}
OFFER_FORMATS = FORMATS | {"NZB", "Torrent"}
JOB_STATES = {
    "awaiting_approval",
    "awaiting_selection",
    "queued",
    "resolving",
    "downloading",
    "staged",
    "publishing",
    "importing",
    "imported",
    "failed",
    "cancelled",
    "rejected",
}


def _normal(value):
    return re.sub(
        r"[\W_]+", " ", unicodedata.normalize("NFKC", value).casefold()
    ).strip()


def _authors_match(value, authors):
    return any(
        sorted(_normal(value).split()) == sorted(_normal(author).split())
        for author in authors
    )


def validate_request(
    title, author=None, book_format=None, continuation_id=None, choice=None
):
    title = text(title)
    if author is not None:
        author = text(author, 300)
    if book_format is not None and (
        not isinstance(book_format, str) or book_format not in FORMATS
    ):
        raise BookError("invalid_arguments")
    if choice is not None and (
        type(choice) is not int
        or not 1 <= choice <= MAX_CHOICES
        or continuation_id is None
    ):
        raise BookError("invalid_arguments")
    return title, author, book_format


def _envelope(answer, evidence, continuation_id=None, completed=True):
    return {
        "answer": answer,
        "completed": completed,
        "tool_calls": 0,
        "observations": [evidence],
        "continuation_id": continuation_id,
    }


def _failure(code, *, uncertain=False):
    descriptions = {
        "not_configured": "NextGen credentials or address are not configured",
        "invalid_auth": "NextGen login failed",
        "forbidden": "the NextGen account lacks permission or its CSRF check failed",
        "not_available": "NextGen Book Sources is unavailable or not enabled for this account",
        "rate_limited": "NextGen rate-limited the operation; try later",
        "invalid_arguments": "provide a title, optional author/format, and a returned numbered choice",
        "invalid_continuation": "this book selection expired, was consumed, or belongs to another configuration; start again",
        "library_scope_limited": "the service account does not have the full-library view needed for acquisition",
        "stale_offer": "the selected offer or source is no longer available; start a fresh search",
        "acquisition_unavailable": "NextGen Book Sources is not ready to accept requests",
        "incomplete_library_search": "the library check was incomplete; narrow the title or review NextGen",
        "storage_unavailable": "book request state could not be saved",
    }
    message = descriptions.get(code, "NextGen information could not be verified")
    answer = (
        "Book request outcome is uncertain. Check NextGen before retrying."
        if uncertain
        else f"{message}. No book acquisition job was submitted."
    )
    return _envelope(
        answer,
        {
            "media_type": "book",
            "reason": code,
            "submission": {"submitted": None if uncertain else False},
        },
        completed=False,
    )


def lookup_books(query):
    try:
        client = get_client()
        result = client.search_library(text(query))
        items = result["items"][:25]
        count = len(items)
        if not result["complete"]:
            answer = f"Partial NextGen library search: showing {count} matching records visible to the service account; the search is incomplete."
        elif not result["total"]:
            answer = "No matching books were found in the library visible to the NextGen service account."
        else:
            answer = f"Found {result['total']} matching book records visible to the NextGen service account; showing {count}."
        if items:
            answer += " " + "; ".join(
                f"{item['title']} — {', '.join(item['authors']) or 'author not supplied'} ({', '.join(item['formats']) or 'no files'})"
                for item in items
            )
        evidence = {
            **result,
            "items": items,
            "display_omitted": max(0, len(result["items"]) - count),
        }
        return _envelope(answer, {"tool": "search_books", "result": evidence})
    except BookError as exc:
        return _failure(exc.code)


def _existing(client, title, author, book_format):
    library = client.search_library(title)
    if not library["complete"]:
        raise BookError("incomplete_library_search")
    return [
        item
        for item in library["items"]
        if _normal(item["title"]) == _normal(title)
        and (author is None or _authors_match(author, item["authors"]))
        and (book_format in item["formats"] if book_format else bool(item["formats"]))
    ]


def _public(candidate, number):
    return {
        "choice": number,
        **{
            key: candidate[key]
            for key in ("title", "authors", "languages", "format", "source")
        },
    }


def _collect(client, title, author, book_format, caps):
    """Use only server-issued search/navigation selections, never source URLs."""
    candidates, seen, warnings = [], set(), []
    query = title + (" " + author if author and len(title) + len(author) < 499 else "")
    for connection in caps["connections"][:4]:
        try:
            root = client.catalog(connection["id"])
            searches = root.get("searches", [])
            if not isinstance(searches, list):
                raise BookError("invalid_response")
            pages = []
            if searches:
                if len(searches) > 2:
                    warnings.append("some_search_templates_not_queried")
                for search in searches[:2]:
                    if not isinstance(search, dict):
                        raise BookError("invalid_response")
                    pages.append(
                        client.catalog(
                            connection["id"],
                            selection=opaque(search.get("selection")),
                            query=query,
                        )
                    )
            else:
                pages.append(root)
                warnings.append("source_has_no_advertised_search")
            selections = set()
            for offset in range(5):
                if offset >= len(pages):
                    break
                page = pages[offset]
                groups = page.get("groups", [])
                if not isinstance(groups, list) or any(
                    not isinstance(group, dict) for group in groups
                ):
                    raise BookError("invalid_response")
                sections = [page, *groups]
                for section in sections:
                    publications = section.get("publications", [])
                    if not isinstance(publications, list):
                        raise BookError("invalid_response")
                    for publication in publications:
                        if not isinstance(publication, dict):
                            raise BookError("invalid_response")
                        label = client.safe_text(publication.get("title"), 1000)
                        # Search results are choices, not an assertion of unique bibliographic identity.
                        if f" {_normal(title)} " not in f" {_normal(label)} ":
                            continue
                        authors = publication.get("authors", [])
                        languages = publication.get("languages", [])
                        offers = publication.get("offers", [])
                        if not all(
                            isinstance(value, list)
                            for value in (authors, languages, offers)
                        ):
                            raise BookError("invalid_response")
                        authors = [client.safe_text(value, 300) for value in authors]
                        if author and authors and not _authors_match(author, authors):
                            continue
                        if (
                            author
                            and not authors
                            and not set(_normal(author).split())
                            <= set(_normal(label).split())
                        ):
                            continue
                        languages = [
                            client.safe_text(value, 100) for value in languages
                        ]
                        publication_id = opaque(publication.get("identity"))
                        for offer in offers:
                            if not isinstance(offer, dict):
                                raise BookError("invalid_response")
                            fmt = offer.get("format")
                            if (
                                not isinstance(fmt, str)
                                or fmt not in OFFER_FORMATS
                                or offer.get("relation")
                                not in ("download", "acquisition")
                            ):
                                continue
                            # Container formats cannot verify an explicitly requested ebook format.
                            if book_format is not None and fmt != book_format:
                                continue
                            offer_identity = opaque(offer.get("identity"))
                            key = (connection["id"], publication_id, offer_identity)
                            if key in seen:
                                continue
                            seen.add(key)
                            if len(candidates) >= MAX_CHOICES:
                                warnings.append("choice_limit")
                                continue
                            candidates.append(
                                {
                                    "title": label,
                                    "authors": authors,
                                    "languages": languages,
                                    "format": fmt,
                                    "source": connection["label"],
                                    "connection_id": connection["id"],
                                    "revision": connection["revision"],
                                    "publication_identity": publication_id,
                                    "offer_identity": offer_identity,
                                    "offer_id": opaque(offer.get("offer_id")),
                                }
                            )
                pagination = page.get("pagination", [])
                if not isinstance(pagination, list):
                    raise BookError("invalid_response")
                for nav in pagination:
                    if not isinstance(nav, dict) or not isinstance(
                        nav.get("relations", []), list
                    ):
                        raise BookError("invalid_response")
                    if "next" not in nav.get("relations", []):
                        continue
                    token = opaque(nav.get("selection"))
                    if token in selections:
                        warnings.append("pagination_repeated")
                        continue
                    selections.add(token)
                    if len(pages) >= 5:
                        warnings.append("source_page_limit")
                        continue
                    pages.append(client.catalog(connection["id"], selection=token))
        except BookError as exc:
            warnings.append(exc.code)
    if len(caps["connections"]) > 4:
        warnings.append("source_limit")
    if len(candidates) > MAX_CHOICES:
        warnings.append("choice_limit")
    return candidates[:MAX_CHOICES], sorted(set(warnings))


def initialize_book_journal(storage):
    with closing(sqlite3.connect(storage.database_path)) as connection, connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS book_request_journal (
            artifact_key TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK(status IN ('submitting','submitted','uncertain','rejected')),
            job_id TEXT, remote_state TEXT, created_at TEXT NOT NULL)""")


def _reserve(storage, key, identifier):
    try:
        with closing(sqlite3.connect(storage.database_path)) as connection, connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                """INSERT OR IGNORE INTO book_request_journal
                (artifact_key, request_id, status, created_at) VALUES (?, ?, 'submitting', ?)""",
                (key, identifier, datetime.now(UTC).isoformat()),
            )
            if cursor.rowcount == 1:
                return None
            prior = dict(
                connection.execute(
                    "SELECT * FROM book_request_journal WHERE artifact_key=?", (key,)
                ).fetchone()
            )
            if prior["status"] == "rejected":
                connection.execute(
                    "UPDATE book_request_journal SET request_id=?, status='submitting', created_at=? WHERE artifact_key=?",
                    (identifier, datetime.now(UTC).isoformat(), key),
                )
                return None
            return prior
    except sqlite3.Error:
        raise BookError("storage_unavailable") from None


def _record(storage, key, status, job_id=None, remote_state=None):
    try:
        with closing(sqlite3.connect(storage.database_path)) as connection, connection:
            connection.execute(
                "UPDATE book_request_journal SET status=?, job_id=?, remote_state=? WHERE artifact_key=?",
                (status, job_id, remote_state, key),
            )
    except sqlite3.Error:
        # The durable submitting claim still blocks replay if this update fails.
        pass


def _owned_result(matches):
    return _envelope(
        "Matching book files are already in the library visible to the NextGen account. No book acquisition job was submitted.",
        {
            "media_type": "book",
            "reason": "already_in_library",
            "matches": matches,
            "submission": {"submitted": False},
        },
    )


def acquire_book(
    question,
    title,
    *,
    author=None,
    book_format=None,
    continuation_id=None,
    choice=None,
    storage,
):
    """Prepare source choices, or submit exactly one stored choice when enabled."""
    try:
        title, author, book_format = validate_request(
            title, author, book_format, continuation_id, choice
        )
        client = get_client()
        with client.session():
            if client.library_mode != "monolibrary":
                raise BookError("library_scope_limited")
            if continuation_id is None:
                owned = _existing(client, title, author, book_format)
                if owned:
                    return _owned_result(owned)
                caps = client.capabilities()
                if not caps["available"]:
                    raise BookError("acquisition_unavailable")
                candidates, warnings = _collect(
                    client, title, author, book_format, caps
                )
                if not candidates:
                    return _envelope(
                        "No selectable acquisition offers were found in the configured sources searched. No book acquisition job was submitted.",
                        {
                            "media_type": "book",
                            "reason": "no_selectable_offers",
                            "search_warnings": warnings,
                            "submission": {"submitted": False},
                        },
                    )
                identifier = storage.create_continuation(
                    title,
                    candidates,
                    context={
                        "media_type": "book",
                        "target": client.target,
                        "author": author,
                        "format": book_format,
                    },
                )
                public = [
                    _public(item, index) for index, item in enumerate(candidates, 1)
                ]
                choices = "; ".join(
                    f"{item['choice']}: {item['title']} — {', '.join(item['authors']) or 'author unverified'} — {item['format']} — {item['source']}"
                    for item in public
                )
                return _envelope(
                    "Choose a numbered acquisition offer. "
                    + choices
                    + ". No book acquisition job was submitted.",
                    {
                        "media_type": "book",
                        "reason": "offer_selection_required",
                        "candidates": public,
                        "search_warnings": warnings,
                        "submission": {"submitted": False},
                    },
                    identifier,
                )
            record = storage.get_continuation(continuation_id)
            context = record.get("context", {}) if record else {}
            if (
                context.get("media_type") != "book"
                or context.get("target") != client.target
            ):
                raise BookError("invalid_continuation")
            candidates = record["candidates"]
            if choice is None:
                match = re.fullmatch(
                    r"(?:option |choice |number )?(\d{1,2})[.!]?",
                    question.strip().lower(),
                )
                choice = int(match[1]) if match else None
            if type(choice) is not int or not 1 <= choice <= len(candidates):
                return _envelope(
                    "Choose one of the returned offer numbers. No book acquisition job was submitted.",
                    {
                        "reason": "offer_selection_required",
                        "candidates": [
                            _public(item, i) for i, item in enumerate(candidates, 1)
                        ],
                        "submission": {"submitted": False},
                    },
                    continuation_id,
                )
            selected = candidates[choice - 1]
            selected_format = (
                selected["format"]
                if selected["format"] in FORMATS
                else context.get("format")
            )
            owned = _existing(
                client, record["title"], context.get("author"), selected_format
            )
            if owned:
                storage.consume_continuation(continuation_id)
                return _owned_result(owned)
            caps = client.capabilities()
            if not caps["available"] or not any(
                connection["id"] == selected["connection_id"]
                and connection["revision"] == selected["revision"]
                for connection in caps["connections"]
            ):
                raise BookError("stale_offer")
            if storage.consume_continuation(continuation_id) is None:
                raise BookError("invalid_continuation")
            evidence = {"media_type": "book", "selected": _public(selected, choice)}
            if not auto_request_enabled():
                evidence.update(
                    reason="auto_request_disabled",
                    submission={"submitted": False, "reason": "dry_run"},
                )
                return _envelope(
                    "Book acquisition is disabled. The selected offer was evaluated; no book acquisition job was submitted.",
                    evidence,
                )
            key = hashlib.sha256(
                json.dumps(
                    [
                        client.target,
                        selected["connection_id"],
                        selected["publication_identity"],
                        selected["offer_identity"],
                    ]
                ).encode()
            ).hexdigest()
            prior = _reserve(storage, key, continuation_id)
            if prior is not None:
                if prior["status"] == "submitted":
                    evidence.update(
                        reason="already_requested",
                        submission={
                            "submitted": False,
                            "existing_job_id": prior["job_id"],
                            "existing_state": prior["remote_state"],
                        },
                    )
                    return _envelope(
                        "This acquisition offer already has a recorded NextGen request. No new job was submitted.",
                        evidence,
                    )
                return _failure("submission_uncertain", uncertain=True)
            if not auto_request_enabled():
                _record(storage, key, "rejected")
                return _envelope(
                    "Book acquisition is disabled. No book acquisition job was submitted.",
                    {
                        **evidence,
                        "reason": "auto_request_disabled",
                        "submission": {"submitted": False, "reason": "dry_run"},
                    },
                )
            try:
                response = client.submit(
                    selected["connection_id"], selected["offer_id"], continuation_id
                )
            except BookError as exc:
                # Preserve the claim even for a definite rejection: no automatic retry.
                _record(storage, key, "uncertain" if exc.uncertain else "rejected")
                return _failure(exc.code, uncertain=exc.uncertain)
            job_id = response.get("id") if isinstance(response, dict) else None
            state = response.get("state") if isinstance(response, dict) else None
            if (
                not isinstance(job_id, str)
                or not re.fullmatch(
                    r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
                    job_id,
                )
                or not isinstance(state, str)
                or state not in JOB_STATES
            ):
                _record(storage, key, "uncertain")
                return _failure("submission_uncertain", uncertain=True)
            _record(storage, key, "submitted", job_id, state)
            evidence.update(
                reason=None,
                submission={"submitted": True, "job_id": job_id, "state": state},
            )
            return _envelope(
                f"NextGen accepted book acquisition job {job_id}; its state is {state}. This acknowledges the request, not download or import completion.",
                evidence,
            )
    except BookError as exc:
        return _failure(exc.code, uncertain=exc.uncertain)
    except sqlite3.Error:
        return _failure("storage_unavailable")
