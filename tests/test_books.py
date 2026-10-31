"""CWNG reads, LazyLibrarian-only writes, exact identity and durable claims."""

import sqlite3
from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations import books
from planelocket_agent.integrations.calibre_web import BookError
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


def entry(identifier="OL123W", status="Skipped"):
    return {
        "book_id": identifier,
        "title": "Example Book",
        "authors": ["Example Author"],
        "year": "2020",
        "isbn": "9780000000000",
        "language": "eng",
        "source": "LazyLibrarian",
        "status": status,
    }


class Library:
    target = "cwng-account"
    library_mode = "monolibrary"

    def __init__(self):
        self.items = []
        self.complete = True
        self.queries = []

    def session(self):
        return nullcontext(self)

    def search_library(self, query):
        self.queries.append(query)
        return {
            "items": deepcopy(self.items),
            "total": len(self.items),
            "complete": self.complete,
        }


class LazyLibrarian:
    target = "ll-server-key"

    def __init__(self):
        self.rows = []
        self.skipped = 0
        self.results = [{**entry(), "source": "OpenLibrary"}]
        self.configs = {
            "BOOK_API": "OpenLibrary",
            "NEWAUDIO_STATUS": "Skipped",
            "NEWBOOK_STATUS": "Skipped",
        }
        self.writes = []
        self.error = None
        self.bad_status = False
        self.bad_add = False
        self.post_read_error = False

    def session(self):
        return nullcontext(self)

    def inventory(self):
        return deepcopy(self.rows)

    def config(self, name):
        return self.configs[name]

    def find(self, query):
        assert query == "Example Book"
        return {
            "items": deepcopy(self.results),
            "records_received": len(self.results) + self.skipped,
            "records_skipped": self.skipped,
        }

    def add(self, identifier, source):
        self.writes.append(("add", identifier, source))
        if self.error:
            raise self.error
        self.rows.append(entry(identifier))
        if self.bad_add:
            self.rows[0]["title"] = "Wrong title"
        return True

    def queue(self, identifier):
        self.writes.append(("queue", identifier, "eBook"))
        if self.error:
            raise self.error
        self.rows[0]["status"] = "Wanted"
        return "OK"

    def status(self, identifier):
        if self.post_read_error:
            raise BookError("ll_service_unavailable")
        return {
            "title": "Example Book",
            "status": "Skipped" if self.bad_status else "Wanted",
        }


@pytest.fixture
def setup(tmp_path, monkeypatch):
    storage = SeerrRequestStorage(tmp_path / "requests.sqlite3")
    storage.initialize()
    books.initialize_book_journal(storage)
    library, remote = Library(), LazyLibrarian()
    monkeypatch.setattr(books, "get_library", lambda: library)
    monkeypatch.setattr(books, "get_client", lambda: remote)
    monkeypatch.setattr(api, "seerr_storage", storage)
    monkeypatch.setenv("LAZYLIBRARIAN_AUTO_REQUEST", "false")
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    monkeypatch.setenv(
        "CWNG_AUTO_REQUEST", "true"
    )  # This obsolete switch has no authority.
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    return library, remote, storage, monkeypatch


def ask(setup, **fields):
    return books.acquire_book(
        "Get Example Book", "Example Book", storage=setup[2], **fields
    )


def select(setup, identifier=None, **fields):
    identifier = identifier or ask(setup)["continuation_id"]
    return ask(setup, continuation_id=identifier, choice=1, **fields)


def outcome(result):
    return result["observations"][0]


def enable(setup):
    setup[3].setenv("LAZYLIBRARIAN_AUTO_REQUEST", "true")


def test_cwng_lookup_is_independent_of_ll_and_owned_stops_writes(setup):
    setup[0].items = [
        {
            "id": 1,
            "title": "Example Book",
            "authors": ["Example Author"],
            "formats": ["EPUB"],
            "series": None,
        }
    ]
    assert books.lookup_books("Example")["completed"]
    assert outcome(ask(setup))["reason"] == "already_in_library"
    assert not setup[1].writes
    with patch.object(
        books, "get_client", side_effect=AssertionError("No LL call on lookup")
    ):
        assert books.lookup_books("Example")["completed"]


def test_explicit_bibliographic_choice_even_for_one_match(setup):
    result = ask(setup)
    assert result["continuation_id"]
    assert outcome(result)["reason"] == "book_selection_required"
    assert outcome(result)["candidates"][0]["source"] == "OpenLibrary"
    assert outcome(result)["search_complete"] is False
    assert "OL123W" not in str(result)
    assert not setup[1].writes


def test_ll_flag_is_independent_and_dry_run_consumes_choice(setup):
    token = ask(setup)["continuation_id"]
    assert outcome(select(setup, token))["submission"]["reason"] == "dry_run"
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"
    assert not setup[1].writes


def test_new_book_add_queue_and_verified_wanted(setup):
    enable(setup)
    result = select(setup)
    assert outcome(result)["submission"] == {
        "submitted": True,
        "book_id": "OL123W",
        "status": "Wanted",
    }
    assert setup[1].writes == [
        ("add", "OL123W", "OpenLibrary"),
        ("queue", "OL123W", "eBook"),
    ]
    assert "does not confirm a download" in result["answer"]
    assert outcome(ask(setup))["reason"] == "already_requested"
    assert len(setup[1].writes) == 2


def test_existing_skipped_book_only_queues_ebook_and_preserves_audio_defaults(setup):
    enable(setup)
    setup[1].rows = [entry()]
    setup[1].configs["NEWAUDIO_STATUS"] = "Wanted"
    assert outcome(select(setup))["submission"]["submitted"] is True
    assert setup[1].writes == [("queue", "OL123W", "eBook")]


@pytest.mark.parametrize(
    "status,reason",
    [
        ("Wanted", "already_requested"),
        ("Snatched", "already_requested"),
        ("Open", "already_in_library"),
        ("Have", "already_in_library"),
        ("Ignored", "ll_status_blocked"),
        ("Unknown", "ll_status_blocked"),
    ],
)
def test_existing_states_block_writes(setup, status, reason):
    enable(setup)
    setup[1].rows = [entry(status=status)]
    assert outcome(ask(setup))["reason"] == reason
    assert not setup[1].writes


def test_new_book_cannot_inherit_audiobook_request(setup):
    enable(setup)
    token = ask(setup)["continuation_id"]
    setup[1].configs["NEWAUDIO_STATUS"] = "Wanted"
    assert outcome(select(setup, token))["reason"] == "ll_audio_default_unsafe"
    assert not setup[1].writes


def test_selected_metadata_is_authoritative_and_key_rotation_rejects_old_token(setup):
    enable(setup)
    token = ask(setup)["continuation_id"]
    result = books.acquire_book(
        "option 1", "Caller replacement", storage=setup[2], continuation_id=token
    )
    assert outcome(result)["submission"]["submitted"] is True
    assert setup[0].queries[-1] == "Example Book"
    token = setup[2].create_continuation(
        "Example Book",
        [entry()],
        context={
            "media_type": "book",
            "backend": "lazylibrarian",
            "target": "old-target",
        },
    )
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"


def test_source_change_and_remote_identity_change_block_submission(setup):
    enable(setup)
    token = ask(setup)["continuation_id"]
    setup[1].configs["BOOK_API"] = "HardCover"
    assert outcome(select(setup, token))["reason"] == "ll_source_changed"
    setup[1].configs["BOOK_API"] = "OpenLibrary"
    setup[1].results[0]["authors"] = ["Other Author"]
    assert outcome(select(setup, token))["reason"] == "ll_identity_changed"
    assert not setup[1].writes


def test_library_arrival_and_ll_status_are_rechecked(setup):
    enable(setup)
    token = ask(setup)["continuation_id"]
    setup[1].rows = [entry(status="Snatched")]
    assert outcome(select(setup, token))["reason"] == "already_requested"
    assert not setup[1].writes


def test_incomplete_library_and_inventory_block_absence(setup):
    enable(setup)
    setup[0].complete = False
    assert outcome(ask(setup))["reason"] == "incomplete_library_search"
    assert "Partial" in books.lookup_books("Example")["answer"]
    setup[0].complete = True
    with patch.object(
        setup[1], "inventory", side_effect=BookError("ll_incomplete_inventory")
    ):
        assert outcome(ask(setup))["reason"] == "ll_incomplete_inventory"
    assert not setup[1].writes


def test_specific_format_constraint_is_not_silently_dropped(setup):
    enable(setup)
    assert outcome(ask(setup, book_format="EPUB"))["reason"] == "format_not_supported"
    assert not setup[1].writes


@pytest.mark.parametrize("fault", ["bad_status", "post_read_error", "bad_add"])
def test_partial_or_unverified_write_stays_uncertain_and_cannot_repeat(setup, fault):
    enable(setup)
    remote = setup[1]
    setattr(remote, fault, True)
    if fault != "bad_add":
        remote.rows = [entry()]
    assert outcome(select(setup))["submission"]["submitted"] is None
    count = len(remote.writes)
    # A fresh UI search cannot bypass the durable claim after an ambiguous write.
    remote.rows = [entry()]
    setattr(remote, fault, False)
    assert outcome(select(setup))["submission"]["submitted"] is None
    assert len(remote.writes) == count


def test_timeout_never_replays_add_and_definite_rejection_needs_new_choice(setup):
    enable(setup)
    remote = setup[1]
    remote.error = BookError("ll_invalid_auth")
    assert outcome(select(setup))["submission"]["submitted"] is False
    remote.error = BookError("ll_cannot_connect", uncertain=True)
    assert outcome(select(setup))["submission"]["submitted"] is None
    remote.error = None
    assert outcome(select(setup))["submission"]["submitted"] is None
    assert len(remote.writes) == 2


def test_durable_success_blocks_repeat_even_if_remote_status_later_skipped(setup):
    enable(setup)
    select(setup)
    setup[1].rows = [entry()]
    assert outcome(select(setup))["reason"] == "already_requested"
    assert len(setup[1].writes) == 2


def test_old_cwng_movie_tv_and_expired_tokens_are_rejected(setup):
    for context in (
        {"media_type": "movie"},
        {"media_type": "tv"},
        {"media_type": "book", "target": "old-cwng"},
    ):
        token = setup[2].create_continuation("Example Book", [], context=context)
        assert outcome(select(setup, token))["reason"] == "invalid_continuation"
    token = ask(setup)["continuation_id"]
    with sqlite3.connect(setup[2].database_path) as connection:
        connection.execute(
            "UPDATE acquisition_continuations SET expires_at='2000-01-01' WHERE id=?",
            (token,),
        )
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"
    assert not setup[1].writes


def test_choice_cap_invalid_reply_and_author_filter(setup):
    setup[1].results = [{**entry(str(i)), "source": "OpenLibrary"} for i in range(30)]
    result = ask(setup, author="Example Author")
    assert len(outcome(result)["candidates"]) == 20
    assert outcome(result)["candidates_omitted"] == 10
    result = ask(setup, continuation_id=result["continuation_id"])
    assert result["continuation_id"]
    assert not setup[1].writes
    assert outcome(ask(setup, author="Other Author"))["reason"] == "no_matching_books"


def test_atomic_journal_and_additive_storage(setup):
    from concurrent.futures import ThreadPoolExecutor

    storage = setup[2]
    movie = storage.create_continuation("Movie", [])
    books.initialize_book_journal(storage)
    assert storage.get_continuation(movie)["title"] == "Movie"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: books._reserve(storage, "same", str(uuid4())), range(2))
        )
    assert sum(r is None for r in results) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"format": "AZW3"},
        {"choice": True},
        {"choice": 0},
        {"choice": 21},
        {"choice": 1},
        {"continuation_id": "invented"},
        {"book_id": "invented"},
        {"url": "https://untrusted.test"},
        {"title": " "},
        {"author": " "},
    ],
)
def test_api_validation_without_writes(setup, fields):
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        response = client.post(
            "/books/acquire",
            json={"question": "get", "title": "Example Book", **fields},
        )
    assert (
        response.status_code == 422
        or outcome(response.json())["reason"] == "invalid_arguments"
    )
    assert not setup[1].writes


def test_protected_api_routes_and_cross_media_replay_do_not_use_model(setup):
    with (
        TestClient(api.app) as client,
        patch.object(api.PlaneLocketAgent, "investigate") as model,
    ):
        assert client.post("/books/search", json={"query": "Example"}).status_code in (
            401,
            403,
        )
        client.headers["Authorization"] = "Bearer test-token"
        assert client.post("/books/search", json={"query": "Example"}).json()[
            "completed"
        ]
        result = client.post(
            "/books/acquire", json={"question": "get", "title": "Example Book"}
        ).json()
        token = result["continuation_id"]
        response = client.post(
            "/books/acquire",
            json={"question": "1", "title": "Example Book", "continuation_id": token},
        )
        assert outcome(response.json())["submission"]["reason"] == "dry_run"
        token = ask(setup)["continuation_id"]
        assert (
            client.post(
                "/investigate",
                json={
                    "question": "1",
                    "intent": "acquire",
                    "title": "Example Book",
                    "continuation_id": token,
                },
            ).status_code
            == 422
        )
        model.assert_not_called()


def test_policy_rechecked_after_journal_reservation(setup):
    with patch.object(books, "auto_request_enabled", side_effect=[True, False]):
        assert outcome(select(setup))["reason"] == "auto_request_disabled"
    assert not setup[1].writes


def test_library_arrival_at_selection_prevents_ll_request(setup):
    enable(setup)
    token = ask(setup)["continuation_id"]
    setup[0].items = [
        {
            "id": 1,
            "title": "Example Book",
            "authors": ["Example Author"],
            "formats": ["EPUB"],
            "series": None,
        }
    ]
    assert outcome(select(setup, token))["reason"] == "already_in_library"
    assert not setup[1].writes


def test_cannot_request_missing_local_record_or_id_collision(setup):
    enable(setup)
    setup[1].rows = [entry()]
    token = ask(setup)["continuation_id"]
    setup[1].rows = []
    assert outcome(select(setup, token))["reason"] == "ll_identity_changed"
    setup[1].rows = [{**entry(), "authors": ["Different Author"]}]
    assert outcome(select(setup, token))["reason"] == "ll_identity_changed"
    assert not setup[1].writes


def test_new_record_already_wanted_by_defaults_is_not_queued_twice(setup):
    enable(setup)
    remote = setup[1]
    original_add = remote.add

    def add(identifier, source):
        original_add(identifier, source)
        remote.rows[0]["status"] = "Wanted"

    remote.add = add
    assert outcome(select(setup))["submission"]["submitted"] is True
    assert remote.writes == [("add", "OL123W", "OpenLibrary")]


def test_disabling_policy_after_add_prevents_queue_and_reports_partial_write(setup):
    remote = setup[1]
    with patch.object(books, "auto_request_enabled", side_effect=[True, True, False]):
        result = select(setup)
    assert outcome(result)["submission"]["submitted"] is None
    assert remote.writes == [("add", "OL123W", "OpenLibrary")]


def test_skipped_metadata_is_reported_without_blocking_valid_choice_or_selection(setup):
    setup[1].skipped = 1
    first = ask(setup)
    evidence = outcome(first)
    assert evidence["reason"] == "book_selection_required"
    assert evidence["metadata_records_skipped"] == 1
    assert evidence["metadata_records_received"] == 2
    assert evidence["search_complete"] is False
    assert "Unusable metadata records skipped: 1" in first["answer"]
    assert (
        outcome(select(setup, first["continuation_id"]))["submission"]["reason"]
        == "dry_run"
    )
    assert not setup[1].writes


def test_all_invalid_external_results_make_no_absence_claim_or_request(setup):
    setup[1].skipped = 1812
    setup[1].results = []
    result = ask(setup)
    assert outcome(result)["metadata_records_skipped"] == 1812
    assert outcome(result)["reason"] == "no_matching_books"
    assert "does not establish" in result["answer"]
    assert not result["continuation_id"]
    assert not setup[1].writes


def test_selected_metadata_disappearing_into_skipped_results_blocks_writes(setup):
    enable(setup)
    first = ask(setup)
    setup[1].results = []
    setup[1].skipped = 1
    result = select(setup, first["continuation_id"])
    assert outcome(result)["reason"] == "ll_identity_changed"
    assert not setup[1].writes
