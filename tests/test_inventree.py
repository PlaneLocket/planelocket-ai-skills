"""Tests for the InvenTree API integration."""

import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import pytest

from planelocket_agent.integrations.inventree import search_parts


class MockResponse:
    """Simulate an HTTP response from InvenTree."""

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_search_parts_pagination(monkeypatch):
    """Verify that all pages of search results are collected."""

    monkeypatch.setenv("INVENTREE_URL", "https://parts.example.com")
    monkeypatch.setenv("INVENTREE_API_TOKEN", "test-token")

    pages = [
        {
            "count": 3,
            "next": "?page=2",
            "results": [
                {"pk": 1, "name": "Part A"},
                {"pk": 2, "name": "Part B"},
            ],
        },
        {
            "count": 3,
            "next": None,
            "results": [
                {"pk": 3, "name": "Part C"},
            ],
        },
    ]

    requested_urls = []

    def mock_open(request, timeout):
        requested_urls.append(request.full_url)
        return MockResponse(pages.pop(0))

    with (
        patch(
            "planelocket_agent.integrations.inventree.build_opener",
            return_value=Mock(open=Mock(side_effect=mock_open)),
        ) as mock_build_opener,
        patch(
            "planelocket_agent.integrations.inventree.json.load",
            side_effect=lambda response: response.data,
        ),
    ):
        results = search_parts("Part")
    assert len(results) == 3
    assert [part["pk"] for part in results] == [1, 2, 3]
    assert len(requested_urls) == 2
    assert requested_urls[1].startswith("https://parts.example.com/")

    from planelocket_agent.integrations.inventree import _RejectRedirects

    mock_build_opener.assert_called_once()

    handlers = mock_build_opener.call_args.args

    assert len(handlers) == 1
    assert isinstance(handlers[0], _RejectRedirects)


def test_redirect_handler_rejects_redirects():
    """Authenticated HTTP requests must not follow redirects automatically."""
    from planelocket_agent.integrations.inventree import _RejectRedirects

    handler = _RejectRedirects()

    result = handler.redirect_request(
        req=None,
        fp=None,
        code=302,
        msg="Found",
        headers={},
        newurl="https://unexpected.example.com/api/part/",
    )

    assert result is None


def test_opener_installs_redirect_handler():
    """Verify the configured HTTP client rejects automatic redirects."""
    from urllib.request import build_opener

    from planelocket_agent.integrations.inventree import _RejectRedirects

    opener = build_opener(_RejectRedirects())

    redirect_handlers = [
        handler for handler in opener.handlers if isinstance(handler, _RejectRedirects)
    ]

    assert len(redirect_handlers) == 1


def test_non_redirect_http_error_propagates(monkeypatch):
    """Non-redirect HTTP errors retain their original status."""
    monkeypatch.setenv("INVENTREE_URL", "https://parts.example.com")
    monkeypatch.setenv("INVENTREE_API_TOKEN", "test-token")

    error = HTTPError(
        url="https://parts.example.com/api/part/",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=None,
    )

    with patch(
        "planelocket_agent.integrations.inventree.build_opener"
    ) as mock_build_opener:
        mock_build_opener.return_value.open.side_effect = error

        with pytest.raises(HTTPError) as exc_info:
            search_parts("resistor")

    assert exc_info.value.code == 401


@pytest.mark.parametrize(
    ("destination", "expected"),
    [
        ("https://parts.example.com/api/part/", True),
        ("https://parts.example.com:443/api/part/", True),
        ("https://parts.example.com:8443/api/part/", False),
        ("https://other.example.com/api/part/", False),
    ],
)
def test_same_origin(destination, expected):
    """Only URLs sharing the same scheme, host, and port are trusted."""
    from planelocket_agent.integrations.inventree import _origin

    assert (_origin("https://parts.example.com") == _origin(destination)) is expected
