import io
import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from planelocket_agent.integrations.seerr import _seerr_get


def test_seerr_get_search(monkeypatch):
    monkeypatch.setenv("SEERR_URL", "http://seerr.test:5055/")
    monkeypatch.setenv("SEERR_API_KEY", "fake-test-key")

    payload = {
        "page": 1,
        "totalPages": 1,
        "totalResults": 1,
        "results": [
            {
                "id": 286217,
                "mediaType": "movie",
                "title": "The Martian",
                "releaseDate": "2015-09-30",
            }
        ],
    }

    response = io.BytesIO(json.dumps(payload).encode("utf-8"))

    with patch("planelocket_agent.integrations.seerr.build_opener") as mock_build:
        mock_build.return_value.open.return_value = response
        result = _seerr_get("search", {"query": "The Martian"})
        request = mock_build.return_value.open.call_args.args[0]
        assert request.get_method() == "GET"
        assert (
            request.full_url == "http://seerr.test:5055/api/v1/search?query=The+Martian"
        )
        assert request.get_header("X-api-key") == "fake-test-key"

    assert result == payload


def test_seerr_get_unauthorized(monkeypatch):
    monkeypatch.setenv("SEERR_URL", "http://seerr.test:5055/")
    monkeypatch.setenv("SEERR_API_KEY", "fake-test-key")
    error = HTTPError(
        "http://seerr.test:5055/api/v1/search", 401, "Unauthorized", None, None
    )

    with patch("planelocket_agent.integrations.seerr.build_opener") as mock_build:
        mock_build.return_value.open.side_effect = error
        with pytest.raises(RuntimeError, match="Seerr returned HTTP 401"):
            _seerr_get("search", {"query": "The Martian"})


def test_seerr_get_connection_failure(monkeypatch):
    monkeypatch.setenv("SEERR_URL", "http://seerr.test:5055/")
    monkeypatch.setenv("SEERR_API_KEY", "fake-test-key")
    error = URLError(ConnectionRefusedError("Connection refused"))
    with patch("planelocket_agent.integrations.seerr.build_opener") as mock_build:
        mock_build.return_value.open.side_effect = error
        with pytest.raises(RuntimeError, match="Seerr couldn't be reached"):
            _seerr_get("search", {"query": "The Martian"})


def test_seerr_get_timeout(monkeypatch):
    monkeypatch.setenv("SEERR_URL", "http://seerr.test:5055/")
    monkeypatch.setenv("SEERR_API_KEY", "fake-test-key")
    error = URLError(TimeoutError("timed out"))
    with patch("planelocket_agent.integrations.seerr.build_opener") as mock_build:
        mock_build.return_value.open.side_effect = error
        with pytest.raises(RuntimeError, match="Seerr request timed out"):
            _seerr_get("search", {"query": "The Martian"})


def test_seerr_get_invalid_json(monkeypatch):
    monkeypatch.setenv("SEERR_URL", "http://seerr.test:5055/")
    monkeypatch.setenv("SEERR_API_KEY", "fake-test-key")
    response = io.BytesIO(b"not valid JSON")
    with patch("planelocket_agent.integrations.seerr.build_opener") as mock_build:
        mock_build.return_value.open.return_value = response
        with pytest.raises(RuntimeError, match="^Seerr returned invalid JSON$"):
            _seerr_get("search", {"query": "The Martian"})
