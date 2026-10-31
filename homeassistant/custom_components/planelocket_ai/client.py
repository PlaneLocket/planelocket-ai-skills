"""Bounded async transport for the existing PlaneLocket AI HTTP API.

This module has no Home Assistant dependency. Never include remote bodies,
URLs, authorization headers or underlying exception messages in errors.
"""

import asyncio
import json
import math
from typing import Any
from uuid import UUID

import aiohttp
from yarl import URL

from .const import (
    HEALTH_TIMEOUT,
    MAX_ANSWER_CHARS,
    MAX_QUESTION_CHARS,
    MAX_RESPONSE_BYTES,
    MAX_TOOL_RESULT_BYTES,
    REQUEST_TIMEOUT,
)


class PlaneLocketError(Exception):
    """A sanitized failure safe to return to a conversation agent."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize_url(value: str) -> str:
    """Accept an HTTPS origin only; never put credentials in a URL."""
    try:
        url = URL(value.strip())
        if (
            url.scheme != "https"
            or not url.host
            or url.user is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query_string
            or url.fragment
            or url.port is None
        ):
            raise ValueError
        return str(url.with_path(""))
    except ValueError, TypeError, AttributeError:
        raise PlaneLocketError("invalid_url") from None


def normalize_token(value: str) -> str:
    """Accept a nonempty printable ASCII bearer credential, without whitespace."""
    if not isinstance(value, str):
        raise PlaneLocketError("invalid_token")
    token = value.strip()
    if not token or len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise PlaneLocketError("invalid_token")
    return token


def validate_question(value: Any) -> str:
    """Validate at the boundary, including callers bypassing the tool schema."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= MAX_QUESTION_CHARS:
        raise PlaneLocketError("invalid_question")
    return value.strip()


def validate_acquisition(title=None, year=None, continuation_id=None):
    """Validate structured acquisition arguments before sending any request."""
    if title is not None and (not isinstance(title, str) or not 1 <= len(title.strip()) <= 500):
        raise PlaneLocketError("invalid_question")
    if year is not None and (type(year) is not int or not 1800 <= year <= 2199):
        raise PlaneLocketError("invalid_question")
    if continuation_id is not None:
        try:
            if (
                not isinstance(continuation_id, str)
                or str(UUID(continuation_id)) != continuation_id
            ):
                raise ValueError
        except ValueError, TypeError, AttributeError:
            raise PlaneLocketError("invalid_question") from None
    if title is None and continuation_id is None:
        raise PlaneLocketError("invalid_question")
    return {
        key: value
        for key, value in {"title": title, "year": year, "continuation_id": continuation_id}.items()
        if value is not None
    }


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))


def _safe_json(value: Any, token: str, depth: int = 0) -> Any:
    """Redact an echoed credential and reject non-finite/deep remote JSON."""
    # HA serializes tool results with orjson, which has bounded depth/integers.
    if depth > 32 or (type(value) is int and not -(2**63) <= value < 2**63):
        raise PlaneLocketError("invalid_response")
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]")
    if isinstance(value, list):
        return [_safe_json(item, token, depth + 1) for item in value]
    if isinstance(value, dict):
        return {
            key.replace(token, "[REDACTED]"): _safe_json(item, token, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, float) and not math.isfinite(value):
        raise PlaneLocketError("invalid_response")
    return value


def bounded_result(payload: Any, token: str) -> dict[str, Any]:
    """Validate the API contract and explicitly mark any omitted evidence."""
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("answer"), str)
        or not payload["answer"].strip()
        or type(payload.get("completed")) is not bool
        or type(payload.get("tool_calls")) is not int
        or not 0 <= payload["tool_calls"] < 2**63
        or not isinstance(payload.get("observations"), list)
        or any(not isinstance(item, dict) for item in payload["observations"])
    ):
        raise PlaneLocketError("invalid_response")

    try:
        answer = _safe_json(payload["answer"], token)
        observations = _safe_json(payload["observations"], token)
        result = {
            "answer": answer[:MAX_ANSWER_CHARS],
            "completed": payload["completed"],
            "tool_calls": payload["tool_calls"],
            "observations": [],
            "answer_truncated": len(answer) > MAX_ANSWER_CHARS,
            "observations_omitted": len(observations),
        }
        continuation_id = payload.get("continuation_id")
        if continuation_id is not None:
            try:
                validate_acquisition(continuation_id=continuation_id)
            except PlaneLocketError:
                raise PlaneLocketError("invalid_response") from None
            result["continuation_id"] = _safe_json(continuation_id, token)
        if not result["completed"]:
            result["error"] = "Investigation incomplete. Do not present this as a verified answer."
        # UTF-8 may need four bytes per character. Reserve room for the envelope.
        while _json_size(result) > MAX_TOOL_RESULT_BYTES:
            result["answer"] = result["answer"][: len(result["answer"]) // 2]
            result["answer_truncated"] = True
        for observation in observations:
            result["observations"].append(observation)
            result["observations_omitted"] -= 1
            if _json_size(result) > MAX_TOOL_RESULT_BYTES:
                result["observations"].pop()
                result["observations_omitted"] += 1
                # Preserve chronological evidence; do not skip an intermediate lookup.
                break
        return result
    except ValueError, RecursionError, OverflowError:
        raise PlaneLocketError("invalid_response") from None


class PlaneLocketClient:
    """Use HA's shared session without owning or closing it."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session = session
        self._url = normalize_url(url)
        self._token = normalize_token(token)

    async def async_health(self) -> None:
        """Check reachability only: /health does not validate the bearer token."""
        payload = await self._async_request("GET", "/health", deadline=HEALTH_TIMEOUT)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise PlaneLocketError("invalid_response")

    async def async_ask(
        self,
        question: str,
        *,
        intent: str | None = None,
        title: str | None = None,
        year: int | None = None,
        continuation_id: str | None = None,
    ) -> dict[str, Any]:
        """Forward one question; never retry a model-backed POST automatically."""
        question = validate_question(question)
        body = {"question": question}
        if intent is not None:
            if intent not in {"acquire", "investigate"}:
                raise PlaneLocketError("invalid_question")
            body["intent"] = intent
        if intent == "acquire":
            body.update(validate_acquisition(title, year, continuation_id))
        elif any(value is not None for value in (title, year, continuation_id)):
            raise PlaneLocketError("invalid_question")
        payload = await self._async_request(
            "POST", "/investigate", deadline=REQUEST_TIMEOUT, body=body
        )
        return bounded_result(payload, self._token)

    async def _async_request(
        self, method: str, path: str, *, deadline: float, body: dict | None = None
    ) -> Any:
        headers = {"Accept": "application/json"}
        kwargs: dict[str, Any] = {}
        if body is not None:
            headers["Authorization"] = f"Bearer {self._token}"
            kwargs["json"] = body
        try:
            # Includes streamed body consumption, not just response headers.
            async with asyncio.timeout(deadline):
                async with self._session.request(
                    method,
                    self._url + path,
                    headers=headers,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=deadline, connect=min(10, deadline)),
                    **kwargs,
                ) as response:
                    if response.status in (401, 403):
                        raise PlaneLocketError("invalid_auth")
                    if response.status != 200:
                        raise PlaneLocketError("service_unavailable")
                    if response.content_type != "application/json":
                        raise PlaneLocketError("invalid_response")
                    if (
                        response.content_length is not None
                        and response.content_length > MAX_RESPONSE_BYTES
                    ):
                        raise PlaneLocketError("response_too_large")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(8192):
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise PlaneLocketError("response_too_large")
                    return json.loads(body)
        except TimeoutError:
            raise PlaneLocketError("timeout") from None
        except aiohttp.ClientError, OSError:
            raise PlaneLocketError("cannot_connect") from None
        except ValueError, UnicodeError, RecursionError:
            raise PlaneLocketError("invalid_response") from None
