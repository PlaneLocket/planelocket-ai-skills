"""CWNG library reads and explicit ebook requests through LazyLibrarian."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import UTC, datetime
from uuid import uuid4

from planelocket_agent.integrations.calibre_web import BookError, text
from planelocket_agent.integrations.calibre_web import get_client as get_library
from planelocket_agent.integrations.lazylibrarian import (
    auto_request_enabled,
    get_client,
)
from planelocket_agent.result_contract import controlled

MAX_CHOICES = 20
FORMATS = {"EPUB", "PDF", "MOBI"}
READY_STATUSES = {"Skipped", "Wanted"}


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
    if "<ll>" in title:
        raise BookError("invalid_arguments")
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
    submission = evidence.get("submission", {})
    if "submitted" in submission and submission["submitted"] is None:
        outcome = "uncertain"
    elif continuation_id:
        outcome = "clarification_required"
    elif not completed or evidence.get("reason") in {
        "auto_request_disabled",
        "ll_status_blocked",
        "no_matching_books",
        "preparation_state_changed",
    }:
        outcome = "blocked"
    else:
        outcome = "completed"
    partial = (
        evidence.get("result", {}).get("complete") is False
        or evidence.get("search_complete") is False
    )
    return controlled(
        {
            "answer": answer,
            "completed": completed,
            "tool_calls": 0,
            "observations": [evidence],
            "continuation_id": continuation_id,
        },
        outcome=outcome,
        partial=partial,
    )


def _failure(code, *, uncertain=False):
    descriptions = {
        "not_configured": "CWNG library credentials or address are not configured",
        "invalid_auth": "CWNG library login failed",
        "ll_not_configured": "LazyLibrarian address or API key is not configured",
        "ll_invalid_auth": "LazyLibrarian rejected API access; a full-access key is required for acquisition",
        "invalid_arguments": "provide a book title, optional author, and a returned numbered choice",
        "invalid_continuation": "this book selection expired, was consumed, or belongs to another configuration; start again",
        "library_scope_limited": "the CWNG account does not have the full-library view required for acquisition checks",
        "incomplete_library_search": "the CWNG library check was incomplete; narrow the title",
        "ll_unsupported_command": "LazyLibrarian does not support the requested API command",
        "ll_forbidden": "the LazyLibrarian API key lacks permission for this operation",
        "ll_search_state_changed": "the ebook state changed before its acquisition search",
        "ll_search_not_configured": "LazyLibrarian has no enabled search methods",
        "ll_timeout": "LazyLibrarian timed out while processing the request",
        "ll_incomplete_inventory": "the LazyLibrarian inventory check was incomplete",
        "ll_identity_changed": "the selected LazyLibrarian book identity changed or could not be verified",
        "ll_source_changed": "LazyLibrarian metadata-source settings changed; start a fresh search",
        "format_not_supported": "LazyLibrarian acquisition follows its configured ebook formats; this API cannot enforce a per-request format",
        "ll_audio_default_unsafe": "LazyLibrarian new-audiobook status must be Skipped or Ignored before adding an ebook through this API",
        "storage_unavailable": "book request state could not be saved",
    }
    answer = (
        "Book request outcome is uncertain. Check LazyLibrarian before retrying."
        if uncertain
        else descriptions.get(code, "Book information could not be verified")
        + ". No acquisition search was submitted."
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
        result = get_library().search_catalog(text(query))
        items = result["items"][:25]
        if not result["complete"]:
            answer = f"Partial CWNG library search: showing {len(items)} records visible to the service account; the search is incomplete."
        elif not result["total"]:
            answer = "No matching books were found in the library visible to the CWNG service account."
        else:
            answer = f"Found {result['total']} matching book records visible to the CWNG service account; showing {len(items)}."
        if items:
            answer += " " + "; ".join(
                f"{i['title']} — {', '.join(i['authors']) or 'author not supplied'} ({', '.join(i['formats']) or 'no files'})"
                for i in items
            )
        return _envelope(
            answer,
            {
                "tool": "search_books",
                "result": {
                    **result,
                    "items": items,
                    "display_omitted": max(0, len(result["items"]) - len(items)),
                },
            },
        )
    except BookError as exc:
        return _failure(exc.code)


def _existing(client, title, author, book_format):
    result = client.search_library(title)
    if not result["complete"]:
        raise BookError("incomplete_library_search")
    return [
        item
        for item in result["items"]
        if _normal(item["title"]) == _normal(title)
        and (author is None or _authors_match(author, item["authors"]))
        and (book_format in item["formats"] if book_format else bool(item["formats"]))
    ]


def _matches(item, title, author):
    return _normal(item["title"]) == _normal(title) and (
        author is None or _authors_match(author, item["authors"])
    )


def _public(candidate, number):
    return {
        "choice": number,
        **{
            key: candidate.get(key)
            for key in ("title", "authors", "year", "isbn", "language", "source")
        },
    }


def _state_result(item):
    status = item["status"]
    if status in READY_STATUSES:
        return None
    if status in {"Have", "Open"}:
        reason, detail = (
            "already_in_library",
            "LazyLibrarian reports this ebook as already owned",
        )
    elif status == "Snatched":
        reason, detail = (
            "already_requested",
            f"LazyLibrarian already lists this ebook as {status}",
        )
    else:
        reason, detail = (
            "ll_status_blocked",
            f"LazyLibrarian status {status} requires review in its UI",
        )
    return _envelope(
        detail + ". No additional acquisition search was submitted.",
        {
            "media_type": "book",
            "reason": reason,
            "book_id": item["book_id"],
            "status": status,
            "submission": {"submitted": False},
        },
    )


def _owned_result(matches):
    return _envelope(
        "Matching book files are already in the library visible to the CWNG account. No acquisition search was submitted.",
        {
            "media_type": "book",
            "reason": "already_in_library",
            "matches": matches,
            "submission": {"submitted": False},
        },
    )


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
    """Resolve a book, prepare its ebook state and request its acquisition search."""
    try:
        title, author, book_format = validate_request(
            title, author, book_format, continuation_id, choice
        )
        library, client = get_library(), get_client()
        with library.session(), client.session():
            if library.library_mode != "monolibrary":
                raise BookError("library_scope_limited")
            target = hashlib.sha256(
                json.dumps([library.target, client.target]).encode()
            ).hexdigest()
            if continuation_id is not None:
                record = storage.get_continuation(continuation_id)
                context = record.get("context", {}) if record else {}
                if (
                    context.get("media_type") != "book"
                    or context.get("backend") != "lazylibrarian"
                    or context.get("target") != target
                ):
                    raise BookError("invalid_continuation")
                if choice is None:
                    match = re.fullmatch(
                        r"(?:option |choice |number )?(\d{1,2})[.!]?",
                        question.strip().lower(),
                    )
                    choice = int(match[1]) if match else None
                candidates = record["candidates"]
                if type(choice) is not int or not 1 <= choice <= len(candidates):
                    return _envelope(
                        "Choose one of the returned book numbers. No acquisition search was submitted.",
                        {
                            "reason": "book_selection_required",
                            "candidates": [
                                _public(c, i) for i, c in enumerate(candidates, 1)
                            ],
                            "submission": {"submitted": False},
                        },
                        continuation_id,
                    )
                selected = candidates[choice - 1]
                # Use the stored selected bibliographic identity, never replacement input.
                title, author = selected["title"], selected["authors"][0]
                book_format = context.get("format")
            owned = _existing(library, title, author, book_format)
            if owned:
                if continuation_id:
                    storage.consume_continuation(continuation_id)
                return _owned_result(owned)
            if book_format is not None:
                raise BookError("format_not_supported")
            inventory = client.inventory()
            if continuation_id is None:
                local = [i for i in inventory if _matches(i, title, author)]
                if len(local) == 1:
                    held = _state_result(local[0])
                    if held:
                        return held
                source = client.config("BOOK_API")
                # Existing LL records take precedence over external metadata IDs.
                search = None if local else client.find(title)
                search_evidence = (
                    {}
                    if search is None
                    else {
                        "metadata_records_received": search["records_received"],
                        "metadata_records_skipped": search["records_skipped"],
                    }
                )
                candidates = local or [
                    i
                    for i in search["items"]
                    if _matches(i, title, author) and i["source"] == source
                ]
                unique = {}
                for item in candidates:
                    unique.setdefault(item["book_id"], item)
                candidates = list(unique.values())
                if not candidates:
                    return _envelope(
                        "No matching book was verified in LazyLibrarian or the usable returned metadata records. "
                        + (
                            f"Unusable metadata records skipped: {search['records_skipped']}. "
                            if search and search["records_skipped"]
                            else ""
                        )
                        + "This does not establish that the book is unavailable. Try a title and author. No acquisition search was submitted.",
                        {
                            "reason": "no_matching_books",
                            **search_evidence,
                            "submission": {"submitted": False},
                        },
                    )
                omitted = max(0, len(candidates) - MAX_CHOICES)
                candidates = candidates[:MAX_CHOICES]
                identifier = storage.create_continuation(
                    title,
                    candidates,
                    context={
                        "media_type": "book",
                        "backend": "lazylibrarian",
                        "target": target,
                        "metadata_source": source,
                        "author": author,
                        "format": book_format,
                    },
                )
                if len(candidates) == 1:
                    # The user's acquisition request already authorizes this book.
                    # Reuse the same fresh checks and durable submission path as a
                    # clarified request; the internal token is not a consent gate.
                    result = acquire_book(
                        question,
                        title,
                        author=author,
                        book_format=book_format,
                        continuation_id=identifier,
                        choice=1,
                        storage=storage,
                    )
                    if search is not None:
                        result["observations"][0].update(
                            search_evidence, search_complete=False
                        )
                        result["control"]["partial"] = True
                        if search["records_skipped"]:
                            result["answer"] += (
                                f" Unusable metadata records skipped: {search['records_skipped']}."
                            )
                    return result
                choices = "; ".join(
                    f"{i}: {c['title']} — {', '.join(c['authors'])} — {c.get('year') or 'date unknown'} — {c['source']}"
                    for i, c in enumerate(candidates, 1)
                )
                return _envelope(
                    "Choose a numbered book for an ebook request through LazyLibrarian. "
                    + choices
                    + (
                        f". Unusable metadata records skipped: {search['records_skipped']}"
                        if search and search["records_skipped"]
                        else ""
                    )
                    + ". No acquisition search was submitted.",
                    {
                        "reason": "book_selection_required",
                        "candidates": [
                            _public(c, i) for i, c in enumerate(candidates, 1)
                        ],
                        "candidates_omitted": omitted,
                        "search_complete": False,
                        **search_evidence,
                        "submission": {"submitted": False},
                    },
                    identifier,
                )
            source = client.config("BOOK_API")
            if source != context["metadata_source"]:
                raise BookError("ll_source_changed")
            current = next(
                (i for i in inventory if i["book_id"] == selected["book_id"]), None
            )
            if current:
                if not _matches(current, selected["title"], selected["authors"][0]):
                    raise BookError("ll_identity_changed")
                held = _state_result(current)
                if held:
                    storage.consume_continuation(continuation_id)
                    return held
            elif selected["source"] == "LazyLibrarian":
                raise BookError("ll_identity_changed")
            else:
                # Refresh metadata before addBook; returned IDs are not globally interchangeable.
                refreshed = client.find(selected["title"])
                if not any(
                    i["book_id"] == selected["book_id"]
                    and i["source"] == selected["source"]
                    and _matches(i, selected["title"], selected["authors"][0])
                    for i in refreshed["items"]
                ):
                    raise BookError("ll_identity_changed")
                if client.config("NEWAUDIO_STATUS") not in {"Skipped", "Ignored"}:
                    raise BookError("ll_audio_default_unsafe")
            if storage.consume_continuation(continuation_id) is None:
                raise BookError("invalid_continuation")
            evidence = {"media_type": "book", "selected": _public(selected, choice)}
            if not auto_request_enabled():
                return _envelope(
                    "Book acquisition is disabled. The selected book was evaluated; no ebook request was submitted.",
                    {
                        **evidence,
                        "reason": "auto_request_disabled",
                        "submission": {"submitted": False, "reason": "dry_run"},
                    },
                )
            # Preparation and search have separate durable claims. Old releases
            # only added/queued books; those records cannot prove search acceptance.
            # An already verified Wanted book needs no replay of preparation writes.
            confirmed = current
            if current is None or current["status"] != "Wanted":
                key = hashlib.sha256(
                    json.dumps(
                        ["lazylibrarian", client.target, selected["book_id"]]
                    ).encode()
                ).hexdigest()
                prior = _reserve(storage, key, continuation_id)
                if prior is not None:
                    if prior["status"] == "submitted":
                        return _envelope(
                            "This ebook was previously prepared, but its state has changed. Review it in LazyLibrarian; no acquisition search was submitted.",
                            {
                                **evidence,
                                "reason": "preparation_state_changed",
                                "submission": {"submitted": False},
                            },
                        )
                    return _failure("submission_uncertain", uncertain=True)
                if not auto_request_enabled():
                    _record(storage, key, "rejected")
                    return _envelope(
                        "Book acquisition is disabled. No acquisition search was submitted.",
                        {
                            **evidence,
                            "reason": "auto_request_disabled",
                            "submission": {"submitted": False, "reason": "dry_run"},
                        },
                    )
                added = False
                queue_acknowledged = False
                try:
                    if current is None:
                        client.add(selected["book_id"], selected["source"])
                        added = True
                        current = next(
                            (
                                i
                                for i in client.inventory()
                                if i["book_id"] == selected["book_id"]
                            ),
                            None,
                        )
                        if current is None or not _matches(
                            current, selected["title"], selected["authors"][0]
                        ):
                            raise BookError("ll_identity_changed", uncertain=True)
                        if current["status"] not in READY_STATUSES:
                            raise BookError("ll_status_blocked", uncertain=True)
                    if current["status"] != "Wanted":
                        if not auto_request_enabled():
                            raise BookError("ll_policy_changed", uncertain=added)
                        client.queue(selected["book_id"])
                        queue_acknowledged = True
                    confirmed = client.status(selected["book_id"])
                    if not _matches(
                        confirmed, selected["title"], selected["authors"][0]
                    ) or confirmed["status"] not in {
                        "Wanted",
                        "Snatched",
                        "Have",
                        "Open",
                    }:
                        raise BookError("ll_queue_unverified", uncertain=True)
                except BookError as exc:
                    uncertain = added or queue_acknowledged or exc.uncertain
                    _record(storage, key, "uncertain" if uncertain else "rejected")
                    return _failure(exc.code, uncertain=uncertain)
                _record(
                    storage, key, "submitted", selected["book_id"], confirmed["status"]
                )
            else:
                # Wanted is eligibility for search, not evidence it ever happened.
                confirmed = client.status(selected["book_id"])
                if not _matches(confirmed, selected["title"], selected["authors"][0]):
                    raise BookError("ll_identity_changed")
            if confirmed["status"] != "Wanted":
                held = _state_result({**confirmed, "book_id": selected["book_id"]})
                if held is not None:
                    return held
                raise BookError("ll_search_state_changed")
            evidence.update(
                book_id=selected["book_id"], book_status_before_search="Wanted"
            )
            search_key = hashlib.sha256(
                json.dumps(
                    ["lazylibrarian-ebook-search", client.target, selected["book_id"]]
                ).encode()
            ).hexdigest()
            # A distinct request ID avoids colliding with the preparation claim.
            prior = _reserve(storage, search_key, str(uuid4()))
            if prior is not None:
                if prior["status"] == "submitted":
                    return _envelope(
                        "LazyLibrarian previously acknowledged a search for this ebook. No additional search was submitted; download status is not verified.",
                        {
                            **evidence,
                            "reason": "already_search_requested",
                            "submission": {
                                "submitted": False,
                                "operation": "searchBook",
                                "previously_acknowledged": True,
                            },
                        },
                    )
                result = _failure("search_submission_uncertain", uncertain=True)
                result["observations"][0].update(evidence, operation="searchBook")
                return result
            if not auto_request_enabled():
                _record(storage, search_key, "rejected")
                return _envelope(
                    "The ebook is Wanted, but book acquisition is disabled. No acquisition search was submitted.",
                    {
                        **evidence,
                        "reason": "auto_request_disabled",
                        "submission": {"submitted": False, "reason": "dry_run"},
                    },
                )
            try:
                client.search(selected["book_id"])
            except BookError as exc:
                _record(
                    storage, search_key, "uncertain" if exc.uncertain else "rejected"
                )
                answer = (
                    "The ebook is Wanted, but the acquisition search outcome is uncertain. Check LazyLibrarian before retrying."
                    if exc.uncertain
                    else "The ebook is Wanted, but LazyLibrarian did not accept its acquisition search. No search was submitted."
                )
                if exc.code == "ll_search_not_configured":
                    answer += " No search methods are enabled in LazyLibrarian."
                return _envelope(
                    answer,
                    {
                        **evidence,
                        "reason": exc.code,
                        "submission": {
                            "submitted": None if exc.uncertain else False,
                            "operation": "searchBook",
                        },
                    },
                    completed=False,
                )
            _record(
                storage, search_key, "submitted", selected["book_id"], "search_accepted"
            )
            return _envelope(
                f"LazyLibrarian accepted an acquisition search for the ebook {selected['title']}. This does not confirm that a download was found or started.",
                {
                    **evidence,
                    "reason": "search_requested",
                    "submission": {
                        "submitted": True,
                        "book_id": selected["book_id"],
                        "operation": "searchBook",
                    },
                },
            )

    except BookError as exc:
        return _failure(exc.code, uncertain=exc.uncertain)
    except sqlite3.Error:
        return _failure("storage_unavailable")
