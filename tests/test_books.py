"""Deterministic book selection, independent policy, and durable request claims."""

from contextlib import nullcontext
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from planelocket_agent import api
from planelocket_agent.integrations import books
from planelocket_agent.integrations.calibre_web import BookError
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage


class NextGen:
    library_mode = "monolibrary"
    target = "dedicated-account-and-server"

    def __init__(self):
        self.items = []
        self.complete = True
        self.posts = []
        self.queries = []
        self.error = None
        self.ack = {"id": str(uuid4()), "state": "awaiting_approval"}
        self.caps = {
            "available": True,
            "connections": [
                {
                    "id": "source-1",
                    "revision": 1,
                    "label": "Configured catalog",
                    "adapter": "opds",
                }
            ],
        }
        self.page = {
            "publications": [
                {
                    "title": "Example Book",
                    "authors": ["Example Author"],
                    "languages": ["en"],
                    "identity": "publication-1",
                    "offers": [
                        {
                            "format": "EPUB",
                            "identity": "edition-epub",
                            "offer_id": "opaque-offer-1",
                            "relation": "download",
                        }
                    ],
                }
            ]
        }

    def session(self):
        return nullcontext(self)

    def search_library(self, query):
        self.queries.append(query)
        return {
            "items": deepcopy(self.items),
            "total": len(self.items),
            "complete": self.complete,
        }

    def capabilities(self):
        return deepcopy(self.caps)

    def catalog(self, connection, *, selection=None, query=None):
        if selection is None:
            return {"searches": [{"selection": "search-token"}]}
        assert selection == "search-token"
        assert query.startswith("Example Book")
        return deepcopy(self.page)

    @staticmethod
    def safe_text(value, maximum=500):
        if not isinstance(value, str) or not value or len(value) > maximum:
            raise BookError("invalid_response")
        return value

    def submit(self, *args):
        self.posts.append(args)
        if self.error:
            raise self.error
        return self.ack


@pytest.fixture
def setup(tmp_path, monkeypatch):
    storage = SeerrRequestStorage(tmp_path / "state.sqlite3")
    storage.initialize()
    books.initialize_book_journal(storage)
    remote = NextGen()
    monkeypatch.setattr(books, "get_client", lambda: remote)
    monkeypatch.setenv("CWNG_AUTO_REQUEST", "false")
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    monkeypatch.setenv("PLANELOCKET_API_TOKEN", "test-token")
    monkeypatch.setattr(api, "seerr_storage", storage)
    return remote, storage, monkeypatch


def ask(setup, **kwargs):
    return books.acquire_book(
        "Get Example Book", "Example Book", storage=setup[1], **kwargs
    )


def outcome(result):
    return result["observations"][0]


def select(setup, token=None, **kwargs):
    token = token or ask(setup)["continuation_id"]
    return ask(setup, continuation_id=token, choice=1, **kwargs)


def owned():
    return {
        "id": 1,
        "title": "Example Book",
        "authors": ["Author, Example"],
        "formats": ["EPUB"],
        "series": None,
    }


def test_read_only_and_owned_stop_before_sources(setup):
    remote, _, _ = setup
    remote.items = [owned()]
    remote.caps = {"available": False, "connections": []}
    assert books.lookup_books("Example")["completed"]
    assert (
        outcome(ask(setup, author="Example Author"))["reason"] == "already_in_library"
    )
    assert not remote.posts


def test_one_offer_still_requires_selection_and_hides_tokens(setup):
    result = ask(setup)
    assert outcome(result)["reason"] == "offer_selection_required"
    assert result["continuation_id"]
    assert "opaque-offer" not in str(result)
    assert "publication-1" not in str(result)
    assert outcome(result)["candidates"][0]["format"] == "EPUB"
    assert not setup[0].posts


def test_book_switch_is_independent_and_dry_run_consumes_selection(setup):
    token = ask(setup)["continuation_id"]
    assert outcome(select(setup, token))["submission"]["reason"] == "dry_run"
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"
    assert not setup[0].posts


def test_ack_and_durable_duplicate_protection(setup):
    remote, _, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    result = select(setup)
    assert outcome(result)["submission"]["state"] == "awaiting_approval"
    assert "not download or import completion" in result["answer"]
    assert len(remote.posts) == 1
    assert outcome(select(setup))["reason"] == "already_requested"
    assert len(remote.posts) == 1


@pytest.mark.parametrize(
    "ack",
    [None, {}, {"id": "wrong", "state": "queued"}, {"id": str(uuid4()), "state": []}],
)
def test_bad_ack_is_uncertain_and_not_reposted(setup, ack):
    remote, _, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    remote.ack = ack
    assert outcome(select(setup))["submission"]["submitted"] is None
    assert outcome(select(setup))["submission"]["submitted"] is None
    assert len(remote.posts) == 1


def test_lost_ack_blocks_new_selection_but_definite_rejection_can_be_reselected(setup):
    remote, _, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    remote.error = BookError("stale_offer")
    assert outcome(select(setup))["submission"]["submitted"] is False
    remote.error = BookError("cannot_connect", uncertain=True)
    assert outcome(select(setup))["submission"]["submitted"] is None
    remote.error = None
    assert outcome(select(setup))["submission"]["submitted"] is None
    assert len(remote.posts) == 2


def test_arriving_book_is_checked_again_before_submit(setup):
    remote, _, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    token = ask(setup)["continuation_id"]
    remote.items = [owned()]
    assert outcome(select(setup, token))["reason"] == "already_in_library"
    assert not remote.posts


def test_stored_title_is_authoritative(setup):
    remote, storage, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    token = ask(setup)["continuation_id"]
    result = books.acquire_book(
        "option 1", "Unrelated replacement", storage=storage, continuation_id=token
    )
    assert outcome(result)["submission"]["submitted"] is True
    assert remote.queries[-1] == "Example Book"


def test_source_revision_and_target_changes_block_old_choices(setup):
    remote, _, env = setup
    env.setenv("CWNG_AUTO_REQUEST", "true")
    token = ask(setup)["continuation_id"]
    remote.caps["connections"][0]["revision"] = 2
    assert outcome(select(setup, token))["reason"] == "stale_offer"
    remote.target = "different-account"
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"
    assert not remote.posts


def test_wrong_media_continuation_rejected(setup):
    token = setup[1].create_continuation("Movie", [], context={"media_type": "movie"})
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"


def test_incomplete_library_blocks_absence_and_personal_view_is_readable_only(setup):
    remote, _, _ = setup
    remote.complete = False
    assert outcome(ask(setup))["reason"] == "incomplete_library_search"
    assert "Partial" in books.lookup_books("Example")["answer"]
    remote.library_mode = "personal_library"
    assert outcome(ask(setup))["reason"] == "library_scope_limited"
    assert books.lookup_books("Example")["completed"]
    assert not remote.posts


def test_ebook_format_does_not_claim_container_contents(setup):
    remote, _, _ = setup
    remote.page["publications"][0]["offers"][0]["format"] = "NZB"
    assert outcome(ask(setup, book_format="EPUB"))["reason"] == "no_selectable_offers"
    assert outcome(ask(setup))["candidates"][0]["format"] == "NZB"


def test_source_failure_is_partial_and_never_a_unique_match(setup):
    setup[0].page = {"groups": "invalid"}
    result = ask(setup)
    assert outcome(result)["reason"] == "no_selectable_offers"
    assert "invalid_response" in outcome(result)["search_warnings"]
    assert not setup[0].posts


def test_choice_limit_and_invalid_choice_preserve_continuation(setup):
    remote, _, _ = setup
    publication = remote.page["publications"][0]
    remote.page["publications"] = [
        dict(publication, identity=f"book-{i}") for i in range(30)
    ]
    result = ask(setup)
    assert len(outcome(result)["candidates"]) == 20
    assert "choice_limit" in outcome(result)["search_warnings"]
    result = ask(setup, continuation_id=result["continuation_id"])
    assert result["continuation_id"]
    assert outcome(result)["reason"] == "offer_selection_required"


@pytest.mark.parametrize(
    "fields",
    [
        {"format": "AZW3"},
        {"choice": True},
        {"choice": 0},
        {"choice": 21},
        {"choice": 1},
        {"continuation_id": "invented"},
        {"url": "https://untrusted.test"},
        {"title": " "},
        {"author": " "},
    ],
)
def test_api_rejects_invalid_book_arguments_without_job(setup, fields):
    with TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client:
        result = client.post(
            "/books/acquire",
            json={"question": "Get Example Book", "title": "Example Book", **fields},
        )
    assert (
        result.status_code == 422
        or outcome(result.json())["reason"] == "invalid_arguments"
    )
    assert not setup[0].posts


def test_api_auth_and_cross_media_replay(setup):
    token = ask(setup)["continuation_id"]
    with TestClient(api.app) as client:
        assert client.post("/books/search", json={"query": "Example"}).status_code in (
            401,
            403,
        )
        assert client.post(
            "/books/acquire", json={"question": "get", "title": "x"}
        ).status_code in (401, 403)
        response = client.post(
            "/investigate",
            headers={"Authorization": "Bearer test-token"},
            json={
                "question": "1",
                "intent": "acquire",
                "title": "Example Book",
                "continuation_id": token,
            },
        )
        assert response.status_code == 422
        assert "matching acquisition tool" in response.json()["detail"]
    assert not setup[0].posts


def test_expired_choice_and_additive_journal_preserve_movie_records(setup):
    import sqlite3

    _, storage, _ = setup
    movie_id = storage.create_continuation("Existing Movie", [])
    token = ask(setup)["continuation_id"]
    books.initialize_book_journal(storage)
    assert storage.get_continuation(movie_id)["title"] == "Existing Movie"
    with sqlite3.connect(storage.database_path) as connection:
        connection.execute(
            "UPDATE acquisition_continuations SET expires_at=? WHERE id=?",
            ("2000-01-01", token),
        )
    assert outcome(select(setup, token))["reason"] == "invalid_continuation"


def test_policy_disabled_during_claim_prevents_post(setup):
    from unittest.mock import patch

    with patch.object(books, "auto_request_enabled", side_effect=[True, False]):
        result = select(setup)
    assert outcome(result)["reason"] == "auto_request_disabled"
    assert not setup[0].posts


def test_api_routes_search_and_continuation_without_model(setup):
    from unittest.mock import patch

    with (
        TestClient(api.app, headers={"Authorization": "Bearer test-token"}) as client,
        patch.object(api.PlaneLocketAgent, "investigate") as model,
    ):
        result = client.post("/books/search", json={"query": "Example"}).json()
        assert result["completed"]
        first = client.post(
            "/books/acquire",
            json={
                "question": "get Example Book",
                "title": "Example Book",
                "format": "EPUB",
            },
        ).json()
        result = client.post(
            "/books/acquire",
            json={
                "question": "option 1",
                "title": "Example Book",
                "choice": 1,
                "continuation_id": first["continuation_id"],
            },
        ).json()
        assert outcome(result)["submission"]["reason"] == "dry_run"
        model.assert_not_called()
    assert not setup[0].posts


def test_atomic_journal_claim_across_workers(setup):
    from concurrent.futures import ThreadPoolExecutor

    storage = setup[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: books._reserve(storage, "same-artifact", str(uuid4())),
                range(2),
            )
        )
    assert sum(result is None for result in results) == 1
    assert (
        next(result for result in results if result is not None)["status"]
        == "submitting"
    )


@pytest.mark.parametrize(
    "publication",
    [
        {
            "title": "Example Book",
            "authors": [],
            "languages": [],
            "identity": "pub",
            "offers": [{"format": [], "relation": "download"}],
        },
        {"title": "Example Book", "authors": "invalid"},
    ],
)
def test_malformed_source_metadata_cannot_create_job(setup, publication):
    setup[0].page = {"publications": [publication]}
    assert outcome(ask(setup))["reason"] == "no_selectable_offers"
    assert not setup[0].posts
