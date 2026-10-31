"""Real loopback HTTP exercises NextGen session/CSRF and bounded transport."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest

from planelocket_agent.integrations import calibre_web as cw


@pytest.fixture
def remote():
    state = {
        "calls": [],
        "logins": 0,
        "csrf": 0,
        "book_reads": 0,
        "job_status": 202,
        "books_status": 200,
        "expire": False,
        "user_id": 7,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, payload, status=200, headers=None, mime="application/json"):
            body = (
                payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlsplit(self.path)
            state["calls"].append(("GET", route.path, dict(self.headers)))
            if route.path == "/api/v1/auth/csrf":
                state["csrf"] += 1
                self.reply(
                    {"csrf_token": f"csrf-{state['csrf']}"},
                    headers={"Set-Cookie": "session=private-session; Path=/; HttpOnly"},
                )
            elif route.path == "/api/v1/books":
                assert "session=private-session" in self.headers.get("Cookie", "")
                state["book_reads"] += 1
                if state["expire"] and state["book_reads"] == 1:
                    self.reply({}, 401)
                elif state["books_status"] == 302:
                    self.reply({}, 302, {"Location": "/stolen"})
                elif "raw" in state:
                    self.reply(state["raw"], mime=state.get("mime", "application/json"))
                else:
                    page = int(parse_qs(route.query)["page"][0])
                    count = state.get("count", 1)
                    start = 0 if state.get("repeat") else (page - 1) * 50
                    items = [
                        dict(
                            id=i + 1,
                            title="Example Book",
                            authors=["Author"],
                            formats=["EPUB"],
                            series=None,
                            cover_url="https://must-not-appear.test",
                        )
                        for i in range(start, min(start + 50, count))
                    ]
                    if state.get("echo_secret"):
                        items[0]["title"] = "test-password private-session csrf-1"
                    self.reply(
                        {"items": items, "total": count, "page": page, "per_page": 50}
                    )
            else:
                self.reply({}, 404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            route = urlsplit(self.path).path
            state["calls"].append(("POST", route, dict(self.headers), payload))
            assert self.headers["X-CSRFToken"] == f"csrf-{state['csrf']}"
            assert "session=private-session" in self.headers.get("Cookie", "")
            if route == "/api/v1/auth/login":
                assert payload == {
                    "username": "test-user",
                    "password": "test-password",
                    "remember": False,
                }
                state["logins"] += 1
                self.reply(
                    {
                        "id": state["user_id"],
                        "name": state.get("name", "test-user"),
                        "library_mode": "monolibrary",
                    }
                )
            elif route == "/api/v1/acquisition/jobs":
                assert set(payload) == {
                    "connection_id",
                    "offer_id",
                    "idempotency_key",
                    "add_to_my_library",
                }
                assert payload["add_to_my_library"] is True
                self.reply(
                    {"id": str(uuid4()), "state": "queued"},
                    state["job_status"],
                    {"Location": "/stolen"} if state["job_status"] == 302 else None,
                )
            else:
                self.reply({}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = cw.CalibreWebClient(
        f"http://127.0.0.1:{server.server_port}", "test-user", "test-password"
    )
    try:
        yield state, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_cookie_login_reuse_csrf_refresh_and_allowlisted_paths(remote):
    state, client = remote
    assert client.search_library("Example")["complete"]
    assert client.search_library("Example")["total"] == 1
    assert state["logins"] == 1
    assert client.library_mode == "monolibrary"
    client.submit("source", "offer", str(uuid4()))
    assert state["csrf"] == 2
    assert (
        sum(call[:2] == ("POST", "/api/v1/acquisition/jobs") for call in state["calls"])
        == 1
    )
    with client.session(), pytest.raises(cw.BookError, match="invalid_arguments"):
        client._request("GET", "https://untrusted.test")


def test_get_reauthenticates_once(remote):
    state, client = remote
    state["expire"] = True
    assert client.search_library("Example")["complete"]
    assert state["logins"] == 2
    assert state["book_reads"] == 2


@pytest.mark.parametrize(
    "status,uncertain",
    [
        (401, False),
        (403, False),
        (404, False),
        (409, False),
        (429, False),
        (500, True),
        (302, True),
    ],
)
def test_job_post_never_retries(remote, status, uncertain):
    state, client = remote
    state["job_status"] = status
    with pytest.raises(cw.BookError) as failure:
        client.submit("source", "offer", str(uuid4()))
    assert failure.value.uncertain is uncertain
    assert (
        sum(call[:2] == ("POST", "/api/v1/acquisition/jobs") for call in state["calls"])
        == 1
    )
    assert not any(call[1] == "/stolen" for call in state["calls"])


def test_get_redirect_is_refused(remote):
    state, client = remote
    state["books_status"] = 302
    with pytest.raises(cw.BookError, match="redirect_refused"):
        client.search_library("Example")
    assert not any(call[1] == "/stolen" for call in state["calls"])


@pytest.mark.parametrize(
    "raw,mime",
    [
        (b"<html>login</html>", "text/html"),
        (b"{broken", "application/json"),
        (b"x" * (cw.MAX_RESPONSE_BYTES + 1), "application/json"),
    ],
)
def test_malformed_or_oversized_response_is_sanitized(remote, raw, mime):
    state, client = remote
    state.update(raw=raw, mime=mime)
    with pytest.raises(cw.BookError) as failure:
        client.search_library("Example")
    assert "test-password" not in str(failure.value)
    assert "<html>" not in str(failure.value)


def test_metadata_projection_and_secret_redaction(remote):
    state, client = remote
    state["echo_secret"] = True
    result = client.search_library("Example")
    assert set(result["items"][0]) == {"id", "title", "authors", "formats", "series"}
    assert "test-password" not in str(result)
    assert "private-session" not in str(result)
    assert "csrf-1" not in str(result)


@pytest.mark.parametrize(
    "count,repeat,complete", [(80, False, True), (80, True, False), (501, False, False)]
)
def test_pagination_proves_completeness_or_refuses_absence(
    remote, count, repeat, complete
):
    state, client = remote
    state.update(count=count, repeat=repeat)
    result = client.search_library("Example")
    assert result["complete"] is complete
    assert len(result["items"]) <= cw.MAX_LIBRARY_RESULTS


def test_wrong_authenticated_account_rejected(remote):
    state, client = remote
    state["name"] = "unexpected-user"
    with pytest.raises(cw.BookError, match="invalid_auth"):
        client.search_library("Example")


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@example.test",
        "https://example.test/path",
        "https://example.test?key=secret",
        "file:///etc/passwd",
    ],
)
def test_configuration_is_origin_only(url):
    with pytest.raises(cw.BookError, match="not_configured"):
        cw.CalibreWebClient(url, "user", "password")


def test_policy_default_and_movie_policy_independence(monkeypatch):
    monkeypatch.delenv("CWNG_AUTO_REQUEST", raising=False)
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    assert not cw.auto_request_enabled()
    monkeypatch.setenv("CWNG_AUTO_REQUEST", "true")
    assert cw.auto_request_enabled()
