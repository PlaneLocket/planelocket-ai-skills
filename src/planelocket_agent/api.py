"""HTTP API for PlaneLocket AI."""

import os
import re
import secrets
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from planelocket_agent.agent import PlaneLocketAgent
from planelocket_agent.config import load_config
from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics
from planelocket_agent.integrations.books import (
    acquire_book,
    initialize_book_journal,
    lookup_books,
)
from planelocket_agent.integrations.seerr_resolver import find_media
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage
from planelocket_agent.integrations.seerr_tv import (
    TVContinuationError,
    continue_tv_request,
    prepare_tv_request,
    tv_result,
    validate_seasons,
)
from planelocket_agent.integrations.seerr_workflow import (
    confirm_movie_request,
    prepare_movie_request,
)
from planelocket_agent.logging_config import configure_logging
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.result_contract import acquisition_response, controlled
from planelocket_agent.tools.dispatcher import ToolDispatcher

load_config()
configure_logging()
seerr_storage = SeerrRequestStorage(
    Path(os.environ.get("SEERR_REQUEST_DB", "./data/seerr_requests.sqlite3"))
)
seerr_storage.initialize()
initialize_book_journal(seerr_storage)

app = FastAPI(
    title="PlaneLocket AI",
    description="Self-hosted AI agent for the PlaneLocket household.",
    version="0.1.0",
)


@app.exception_handler(RequestValidationError)
async def invalid_arguments(_request, exc):
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'] if part != 'body')}: {error['msg']}"
        for error in exc.errors()[:5]
    )
    return JSONResponse(
        status_code=422,
        content=controlled(
            {
                "answer": ("Invalid arguments. " + details)[:1500],
                "completed": False,
                "tool_calls": 0,
                "observations": [],
                "detail": [
                    {key: error[key] for key in ("type", "loc", "msg")}
                    for error in exc.errors()[:5]
                ],
            },
            outcome="blocked",
        ),
    )


@app.exception_handler(HTTPException)
async def rejected_request(_request, exc):
    answer = exc.detail if isinstance(exc.detail, str) else "The request was rejected."
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content=controlled(
            {
                "answer": answer,
                "completed": False,
                "tool_calls": 0,
                "observations": [],
                "detail": exc.detail,
            },
            outcome="blocked",
        ),
    )


bearer_scheme = HTTPBearer()


def require_api_token(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> None:
    """Verify the API bearer token."""

    configured_token = os.environ.get("PLANELOCKET_API_TOKEN")

    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )

    if not secrets.compare_digest(
        credentials.credentials,
        configured_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )


class ConversationMessage(BaseModel):
    """One message from a previous conversation turn."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class InvestigationRequest(BaseModel):
    """A natural-language question submitted to PlaneLocket AI."""

    question: str = Field(min_length=1, max_length=2000)
    intent: Literal["acquire", "investigate"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    year: int | None = Field(default=None, ge=1800, le=2199)
    continuation_id: str | None = None
    media_type: Literal["movie", "tv"] | None = None
    seasons: list[StrictInt] | None = Field(default=None, min_length=1, max_length=100)
    all_seasons: StrictBool = False
    conversation_history: list[ConversationMessage] = Field(
        default_factory=list,
        max_length=10,
    )


class BookSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)


class BookAcquisitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    author: str | None = Field(default=None, min_length=1, max_length=300)
    book_format: Literal["EPUB", "PDF", "MOBI"] | None = Field(
        default=None, alias="format"
    )
    continuation_id: UUID | None = None
    choice: StrictInt | None = Field(default=None, ge=1, le=20)


@app.post("/books/search", dependencies=[Depends(require_api_token)])
def search_book_library(request: BookSearchRequest) -> dict:
    """Read-only book lookup, independent of acquisition intent and model routing."""
    return lookup_books(request.query)


@app.post("/books/acquire", dependencies=[Depends(require_api_token)])
def acquire_book_offer(request: BookAcquisitionRequest) -> dict:
    """LazyLibrarian ebook requests are isolated from movie/TV policy."""
    return acquire_book(
        request.question,
        request.title,
        author=request.author,
        book_format=request.book_format,
        continuation_id=str(request.continuation_id)
        if request.continuation_id
        else None,
        choice=request.choice,
        storage=seerr_storage,
    )


class MediaConfirmationRequest(BaseModel):
    """Identify a pending media request approved by the user."""

    request_id: str


class MediaPreparationRequest(BaseModel):
    """Identify a movie the user wants to acquire."""

    title: str
    year: int | None = None


@app.get("/health")
def health() -> dict[str, str]:
    """Report whether the API is running."""
    return {"status": "ok"}


def acquisition_result(outcome: dict) -> dict:
    """Describe workflow evidence without letting a model invent submission."""
    inspection = outcome["inspection"]
    candidates = inspection.get("candidates", [])
    if (
        "submitted" in outcome.get("submission", {})
        and outcome["submission"]["submitted"] is None
    ):
        answer = "Movie request outcome is uncertain. Check Seerr before retrying."
    elif outcome.get("continuation_id"):
        choices = ", ".join(
            f"{item['title']} ({item.get('year') or 'unknown year'} movie)"
            for item in candidates
        )
        answer = f"Which version: {choices}? No request was submitted."
    elif outcome.get("submission", {}).get("submitted"):
        answer = f"Requested {outcome['title']}."
    else:
        media = inspection.get("media") or {}
        title = media.get("title") or "Movie"
        year = (media.get("releaseDate") or "")[:4]
        identity = f"{title} ({year})" if year else title
        reasons = {
            "auto_request_disabled": "automatic acquisition is disabled",
            "already_available": "already available",
            "already_requested": "already requested",
            "already_in_progress": "already in progress",
            "no_unique_match": "no unique matching movie release",
            "search_too_broad": "search was incomplete; narrow the title",
            "conflicting_year": "conflicting release years",
            "media_identity_changed": "candidate identity changed; start a new search",
        }
        reason = (
            outcome.get("reason")
            or outcome.get("submission", {}).get("reason")
            or "not requestable"
        )
        answer = f"{identity}: {reasons.get(reason, reason)}. No request was submitted."
    return acquisition_response(
        {
            "answer": answer,
            "completed": True,
            "tool_calls": 0,
            "observations": [outcome],
            "continuation_id": outcome.get("continuation_id"),
        },
        outcome,
    )


def _investigate(request: InvestigationRequest) -> dict:
    """Investigate a question using the PlaneLocket AI agent."""

    if request.continuation_id is not None and request.intent == "investigate":
        raise HTTPException(
            status_code=422, detail="Continuation requires acquisition intent"
        )

    if request.media_type == "tv":
        if request.intent != "acquire":
            raise HTTPException(
                status_code=422, detail="TV acquisition requires explicit intent"
            )
        try:
            validate_seasons(request.seasons, request.all_seasons)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        try:
            if request.continuation_id is not None:
                outcome = continue_tv_request(
                    request.continuation_id,
                    request.question,
                    year=request.year,
                    seasons=request.seasons,
                    all_seasons=request.all_seasons,
                    storage=seerr_storage,
                )
            elif request.title and request.title.strip():
                outcome = prepare_tv_request(
                    request.title,
                    request.year,
                    seasons=request.seasons,
                    all_seasons=request.all_seasons,
                    storage=seerr_storage,
                )
            else:
                return controlled(
                    {
                        "answer": "Provide the TV series title. No request was submitted.",
                        "completed": True,
                        "tool_calls": 0,
                        "observations": [],
                    },
                    outcome="clarification_required",
                )
        except TVContinuationError:
            raise HTTPException(
                status_code=400, detail="Invalid, expired or consumed TV continuation"
            ) from None
        except RuntimeError:
            return {
                "answer": "TV availability could not be verified. No request was submitted.",
                "completed": False,
                "tool_calls": 0,
                "observations": [],
            }
        return tv_result(outcome)
    if request.seasons is not None or request.all_seasons:
        raise HTTPException(
            status_code=422, detail="Season selection requires media_type=tv"
        )

    if request.continuation_id is not None:
        record = seerr_storage.get_continuation(request.continuation_id)
        if record is None:
            raise HTTPException(
                status_code=400, detail="Invalid or expired continuation"
            )
        if record.get("context", {}).get("media_type", "movie") != "movie":
            raise HTTPException(
                status_code=422,
                detail="Use the matching acquisition tool for this continuation",
            )
        question = request.question.strip().lower()
        candidates = record.get("candidates", [])
        if not candidates:  # Continuations issued by older servers.
            candidates = find_media(record["title"], media_type="movie").get(
                "candidates", []
            )
        year = request.year
        if year is None and question in {
            "the new one",
            "new one",
            "the newest",
            "newest",
            "latest",
        }:
            years = [
                int(item["year"])
                for item in candidates
                if str(item.get("year", "")).isdigit()
            ]
            year = max(years) if years else None
        if year is None:
            match = re.fullmatch(r"(?:the )?((?:19|20)\d{2})(?: version)?", question)
            year = int(match[1]) if match else None
        selected = [item for item in candidates if str(item.get("year")) == str(year)]
        if year is None or len(selected) != 1:
            return {
                "answer": "Please choose one unique movie release year from the candidates. No request was submitted.",
                "completed": True,
                "tool_calls": 0,
                "observations": [],
                "continuation_id": request.continuation_id,
            }
        record = seerr_storage.consume_continuation(request.continuation_id)
        if record is None:
            raise HTTPException(status_code=409, detail="Continuation already consumed")
        return acquisition_result(
            prepare_movie_request(
                title=record["title"],
                year=year,
                storage=seerr_storage,
                expected_media_id=selected[0].get("media_id"),
            )
        )

    acquisition_requested = request.intent == "acquire" or (
        request.intent is None
        and bool(
            re.search(
                r"\b(?:acquire|download|request|add to (?:my |the )?library)\b"
                r"|^\s*(?:(?:please|go)\s+)*(?:get|add)\s+",
                request.question,
                flags=re.IGNORECASE,
            )
        )
    )
    if acquisition_requested:
        title = request.title
        if title is None:
            # Compatibility for older question-only clients. Complex phrasing
            # asks for clarification rather than relying on arbitrary tool choice.
            match = re.fullmatch(
                r"\s*(?:(?:please|go)\s+)*(?:get|acquire|download|request|add)\s+"
                r"(?:(?:the\s+)?movie\s+)?(.+?)(?:\s+for the household library)?[.!]?\s*",
                request.question,
                flags=re.IGNORECASE,
            )
            title = match[1].strip().strip('"') if match else None
        if not title:
            return controlled(
                {
                    "answer": "Which movie title would you like to acquire? No request was submitted.",
                    "completed": True,
                    "tool_calls": 0,
                    "observations": [],
                },
                outcome="clarification_required",
            )
        return acquisition_result(
            prepare_movie_request(title=title, year=request.year, storage=seerr_storage)
        )

    agent = PlaneLocketAgent(
        skills_directory=Path("skills"),
        client=OllamaClient(),
    )

    dispatcher = ToolDispatcher(LinuxDiagnostics())
    try:
        result = agent.investigate(
            request.question,
            dispatcher,
            conversation_history=[
                message.model_dump() for message in request.conversation_history
            ],
        )
    except ValueError:
        return {
            "answer": "The model returned an invalid or incomplete response. Please try again.",
            "completed": False,
            "tool_calls": 0,
            "observations": [],
        }

    # Source observations are evidence, not authority to create interaction state.
    return controlled(
        {
            "continuation_id": None,
            "answer": result.answer,
            "tool_calls": result.tool_calls,
            "observations": result.observations,
            "completed": result.completed,
        }
    )


@app.post("/investigate", dependencies=[Depends(require_api_token)])
def investigate(request: InvestigationRequest) -> dict:
    result = _investigate(request)
    if "control" in result:
        return result
    return controlled(result)


@app.post("/media/confirm", dependencies=[Depends(require_api_token)])
def confirm_media(request: MediaConfirmationRequest) -> dict:
    """Confirm and submit a pending movie acquisition."""

    return confirm_movie_request(
        request_id=request.request_id,
        storage=seerr_storage,
    )


@app.post("/media/prepare", dependencies=[Depends(require_api_token)])
def prepare_media(request: MediaPreparationRequest) -> dict:
    """Prepare a movie acquisition for confirmation."""

    return prepare_movie_request(
        title=request.title,
        year=request.year,
        storage=seerr_storage,
    )
