"""Real CherryPy-style form API: plain tokens, JSON and no automatic replay."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import pytest

from planelocket_agent.integrations import lazylibrarian as ll
from planelocket_agent.integrations.calibre_web import BookError

KEY = "a" * 32


def row(identifier="OL123W"):
    return {
        "BookID": identifier,
        "BookName": "Example Book",
        "AuthorName": "Example Author",
        "BookDate": "2020",
        "BookIsbn": None,
        "BookLang": "eng",
        "Status": "Skipped",
        "BookFile": "/private/files/book.epub",
        "BookDesc": "untrusted description",
    }


@pytest.fixture
def remote():
    state = {
        "calls": [],
        "http_status": 200,
        "response": None,
        "count": 1,
        "duplicate": False,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            params = parse_qs(
                self.rfile.read(int(self.headers["Content-Length"])).decode(),
                keep_blank_values=True,
            )
            assert self.path == "/api" and "?" not in self.path
            assert params.pop("apikey") == [KEY]
            command = params.pop("cmd")[0]
            state["calls"].append((command, params))
            if state["response"] is not None:
                result = state["response"]
            elif command == "getVersion":
                result = {"Success": True, "current_version": "a0fe7646"}
            elif command == "getAllBooks":
                assert params == {"limit": [str(ll.MAX_BOOKS + 1)]}
                result = [
                    row("OL123W" if state["duplicate"] else f"OL{i}W")
                    for i in range(state["count"])
                ]
            elif command == "findBook":
                result = [
                    dict(
                        bookid="OL123W",
                        bookname="Example Book",
                        authorname="Example Author",
                        bookdate="2020",
                        bookisbn=None,
                        booklang="eng",
                        source="OpenLibrary",
                        booklink="https://must-not-fetch.test",
                    )
                ]
            elif command == "readCFG":
                result = (
                    "[OpenLibrary]" if params["name"] == ["BOOK_API"] else "[Skipped]"
                )
            elif command == "addBook":
                assert params == {
                    "id": ["OL123W"],
                    "source": ["OpenLibrary"],
                    "wait": ["1"],
                }
                result = True
            elif command == "queueBook":
                assert params == {"id": ["OL123W"], "type": ["eBook"]}
                result = "OK"
            else:
                raise AssertionError(command)
            body = (
                result
                if isinstance(result, bytes)
                else (
                    result.encode()
                    if isinstance(result, str)
                    else json.dumps(result).encode()
                )
            )
            self.send_response(state["http_status"])
            self.send_header(
                "Content-Type", "text/html;charset=utf-8"
            )  # LL's actual default
            self.send_header("Content-Length", str(len(body)))
            if state["http_status"] == 302:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = ll.LazyLibrarianClient(f"http://127.0.0.1:{server.server_port}", KEY)
    try:
        yield state, client
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_post_body_auth_plain_tokens_json_and_one_book_commands(remote):
    state, client = remote
    assert client.config("BOOK_API") == "OpenLibrary"
    assert client.config("NEWAUDIO_STATUS") == "Skipped"
    assert client.add("OL123W", "OpenLibrary") is True
    assert client.queue("OL123W") == "OK"
    assert client.status("OL0W") == {
        "title": "Example Book",
        "authors": ["Example Author"],
        "status": "Skipped",
    }
    assert state["calls"][-1][0] == "getAllBooks"
    assert len(state["calls"]) == 5
    assert all(KEY not in str(call) for call in state["calls"])


def test_metadata_projection_drops_private_paths_and_remote_links(remote):
    _, client = remote
    result = client.inventory()[0]
    assert result["title"] == "Example Book"
    assert result["book_id"] == "OL0W"
    assert "/private/" not in str(result)
    assert "description" not in str(result)
    result = client.find("Example Book")["items"][0]
    assert result["source"] == "OpenLibrary"
    assert "https://" not in str(result)


@pytest.mark.parametrize(
    "status,uncertain", [(401, False), (403, False), (500, True), (302, True)]
)
def test_write_http_errors_never_retry_or_follow_redirects(remote, status, uncertain):
    state, client = remote
    state["http_status"] = status
    with pytest.raises(BookError) as failure:
        client.queue("OL123W")
    assert failure.value.uncertain is uncertain
    assert state["calls"] == [("queueBook", {"id": ["OL123W"], "type": ["eBook"]})]
    assert KEY not in str(failure.value)


@pytest.mark.parametrize(
    "response",
    [
        b"<html>login</html>",
        b"{broken",
        b"OK",
        b"false",
        b"x" * (ll.MAX_RESPONSE_BYTES + 1),
    ],
    ids=["html", "broken-json", "bare-ok", "false", "oversized"],
)
def test_add_failures_or_unexpected_tokens_are_not_success(remote, response):
    state, client = remote
    state["response"] = response
    with pytest.raises(BookError) as failure:
        client.add("OL123W", "OpenLibrary")
    assert failure.value.uncertain
    assert len(state["calls"]) == 1
    assert KEY not in str(failure.value)


def test_read_only_key_error_envelope_is_sanitized(remote):
    state, client = remote
    state["response"] = {
        "Success": False,
        "Error": {
            "Code": 405,
            "Message": "Command: readCFG not available with read-only api access key "
            + KEY,
        },
    }
    with pytest.raises(BookError, match="ll_forbidden") as failure:
        client.config("BOOK_API")
    assert not failure.value.uncertain
    assert KEY not in str(failure.value)


@pytest.mark.parametrize("count,duplicate", [(ll.MAX_BOOKS + 1, False), (2, True)])
def test_incomplete_inventory_cannot_prove_absence(remote, count, duplicate):
    state, client = remote
    state.update(count=count, duplicate=duplicate)
    with pytest.raises(BookError, match="ll_incomplete_inventory"):
        client.inventory()


def test_credential_echo_in_metadata_is_redacted(remote):
    state, client = remote
    state["response"] = [{**row(), "BookName": "Book " + KEY}]
    assert KEY not in str(client.inventory())


@pytest.mark.parametrize(
    "command,params",
    [
        ("forceBookSearch", {}),
        ("writeCFG", {"name": "BOOK_API", "value": "GoogleBooks"}),
        ("readCFG", {"name": "SAB_API", "group": "SABnzbd"}),
        ("queueBook", {"id": "OL123W", "type": "AudioBook"}),
        ("addBook", {"id": "one,two", "source": "OpenLibrary", "wait": "1"}),
        ("getAllBooks", {"limit": 0}),
        ("findBook", {"name": "x", "url": "https://bad.test"}),
    ],
)
def test_command_and_argument_allowlist_never_sends(remote, command, params):
    state, client = remote
    with client.session(), pytest.raises(BookError):
        client._call(command, **params)
    assert not state["calls"]


def test_separate_policy_default_and_legacy_switches_have_no_authority(monkeypatch):
    monkeypatch.delenv("LAZYLIBRARIAN_AUTO_REQUEST", raising=False)
    monkeypatch.setenv("SEERR_AUTO_REQUEST", "true")
    monkeypatch.setenv("CWNG_AUTO_REQUEST", "true")
    assert not ll.auto_request_enabled()
    monkeypatch.setenv("LAZYLIBRARIAN_AUTO_REQUEST", "true")
    assert ll.auto_request_enabled()


@pytest.mark.parametrize(
    "payload",
    [
        [
            {
                "bookid": "OL123W",
                "bookname": "Example Book",
                "authorname": "Example Author",
                "source": [],
            }
        ],
        [
            {
                "bookid": KEY,
                "bookname": "Example Book",
                "authorname": "Example Author",
                "source": "OpenLibrary",
            }
        ],
    ],
)
def test_malformed_metadata_or_secret_as_identifier_is_rejected(remote, payload):
    state, client = remote
    state["response"] = payload
    with pytest.raises(BookError, match="ll_invalid_response"):
        client.item(payload[0], external=True)
    result = client.find("Example Book")
    assert result == {"items": [], "records_received": 1, "records_skipped": 1}


def test_configuration_reader_cannot_return_arbitrary_secret_value(remote):
    state, client = remote
    state["response"] = "[" + KEY + "]"
    with pytest.raises(BookError, match="ll_invalid_response"):
        client.config("BOOK_API")


def test_large_external_search_keeps_valid_choices_around_invalid_record(remote):
    state, client = remote
    valid = {**row(), "source": "OpenLibrary"}
    bad = {**valid, "AuthorName": " "}
    payload = [{**valid, "BookID": f"OL{i}W"} for i in range(1812)]
    payload[667] = bad
    state["response"] = payload
    result = client.find("Example Book")
    assert result["records_received"] == 1812
    assert result["records_skipped"] == 1
    assert len(result["items"]) == 1811
    assert result["items"][666]["book_id"] == "OL666W"
    assert result["items"][667]["book_id"] == "OL668W"
    assert "BookFile" not in str(result)


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        [],
        {"source": []},
        {**row(), "source": "OpenLibrary", "BookName": "x" * 1001},
    ],
)
def test_external_bad_rows_are_omitted_but_inventory_validation_stays_strict(
    remote, invalid
):
    state, client = remote
    state["response"] = [{**row(), "source": "OpenLibrary"}, invalid]
    result = client.find("Example Book")
    assert len(result["items"]) == 1
    assert result["records_skipped"] == 1
    with pytest.raises(BookError):
        client.inventory()


@pytest.mark.parametrize("wrapped", [False, True])
def test_read_and_write_timeouts_are_distinguished_without_retries(remote, wrapped):
    from unittest.mock import patch
    from urllib.error import URLError

    _, client = remote
    for command, args, uncertain in [
        ("findBook", {"name": "Example Book"}, False),
        ("queueBook", {"id": "OL123W", "type": "eBook"}, True),
    ]:
        error = TimeoutError("secret must not appear")
        with (
            client.session(),
            patch.object(
                client._opener,
                "open",
                side_effect=URLError(error) if wrapped else error,
            ) as send,
        ):
            with pytest.raises(BookError, match="ll_timeout") as failure:
                client._call(command, **args)
        assert failure.value.uncertain is uncertain
        assert "secret" not in str(failure.value)
        send.assert_called_once()


def test_unregistered_getbook_command_is_never_sent(remote):
    state, client = remote
    with client.session(), pytest.raises(BookError, match="invalid_arguments"):
        client._call("getBook", id="OL123W")
    assert not state["calls"]


@pytest.mark.parametrize(
    "message,code,expected",
    [
        ("Unknown command: getBook, try cmd=help", 405, "ll_unsupported_command"),
        (
            "Command: queueBook not available with read-only api access key, try cmd=help",
            405,
            "ll_forbidden",
        ),
        ("Incorrect API key", 401, "ll_invalid_auth"),
        ("Unrecognized rejection", 405, "ll_request_rejected"),
    ],
)
def test_protocol_errors_distinguish_commands_permissions_and_auth(
    remote, message, code, expected
):
    state, client = remote
    state["response"] = {"Success": False, "Error": {"Code": code, "Message": message}}
    with pytest.raises(BookError, match=expected) as failure:
        client.queue("OL123W")
    assert not failure.value.uncertain
    assert len(state["calls"]) == 1


def test_status_verifies_exact_id_and_refuses_incomplete_inventory(remote):
    state, client = remote
    with pytest.raises(BookError, match="ll_identity_changed"):
        client.status("absent-id")
    state["count"] = ll.MAX_BOOKS + 1
    with pytest.raises(BookError, match="ll_incomplete_inventory"):
        client.status("OL0W")
    assert all(command == "getAllBooks" for command, _ in state["calls"])
