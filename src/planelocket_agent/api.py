"""HTTP API for PlaneLocket AI."""

import os
import re
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from planelocket_agent.agent import PlaneLocketAgent
from planelocket_agent.config import load_config
from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage
from planelocket_agent.integrations.seerr_resolver import find_media
from planelocket_agent.integrations.seerr_workflow import (
    confirm_movie_request,
    prepare_movie_request,
)
from planelocket_agent.logging_config import configure_logging
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.tools.dispatcher import ToolDispatcher

load_config()
configure_logging()
seerr_storage = SeerrRequestStorage(
    Path(os.environ.get("SEERR_REQUEST_DB", "./data/seerr_requests.sqlite3"))
)
seerr_storage.initialize()

app = FastAPI(
    title="PlaneLocket AI",
    description="Self-hosted AI agent for the PlaneLocket household.",
    version="0.1.0",
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

    question: str
    continuation_id: str | None = None
    conversation_history: list[ConversationMessage] = Field(
        default_factory=list,
        max_length=10,
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


@app.post("/investigate", dependencies=[Depends(require_api_token)])
def investigate(request: InvestigationRequest) -> dict:
    """Investigate a question using the PlaneLocket AI agent."""

    if request.continuation_id is not None:
        record = seerr_storage.get_continuation(request.continuation_id)
        if record is None:
            raise HTTPException(status_code=400, detail="Invalid or expired continuation")

        question = request.question.strip().lower()
        if question in {"the new one", "new one", "the newest", "newest", "latest"}:
            resolution = find_media(record["title"], media_type="movie")
            candidates = resolution.get("candidates", [])
            years = sorted(
                {int(item["year"]) for item in candidates if item.get("year")}
            )
            if not years:
                return {"answer": "I couldn't identify a newest release.", "completed": False,
                        "tool_calls": 0, "observations": []}
            year = years[-1]
            if sum(int(item["year"]) == year for item in candidates) != 1:
                return {"answer": "Multiple releases share the newest year.", "completed": False,
                        "tool_calls": 0, "observations": []}
        elif re.fullmatch(r"(?:the )?(?:19|20)\\d{2}(?: version)?", question):
            year = int(re.search(r"(?:19|20)\\d{2}", question).group())
        else:
            return {"answer": "Please specify the release year or say 'the new one'.",
                    "completed": False, "tool_calls": 0, "observations": []}

        record = seerr_storage.consume_continuation(request.continuation_id)
        if record is None:
            raise HTTPException(status_code=409, detail="Continuation already consumed")
        outcome = prepare_movie_request(title=record["title"], year=year,
                                        storage=seerr_storage)
        submitted = outcome.get("submission", {}).get("submitted", False)
        answer = (
            f"Requested {outcome['title']} ({year})." if submitted
            else f"Evaluated {record['title']} ({year}): {outcome['reason'] or 'not submitted'}."
        )
        return {"answer": answer, "completed": True, "tool_calls": 0,
                "observations": [outcome]}

    agent = PlaneLocketAgent(
        skills_directory=Path("skills"),
        client=OllamaClient(),
    )

    dispatcher = ToolDispatcher(LinuxDiagnostics())
    acquisition_requested = bool(
        re.match(
            r"^\s*(?:(?:please|go)\s+)*(?:get|request|download|add)\s+",
            request.question,
            flags=re.IGNORECASE,
        )
    )

    if acquisition_requested:
        dispatcher.bind_media_requests(seerr_storage)

    result = agent.investigate(
        request.question,
        dispatcher,
        conversation_history=[
            message.model_dump() for message in request.conversation_history
        ],
    )

    continuation_ids = [
        observation.get("result", {}).get("continuation_id")
        for observation in result.observations
        if isinstance(observation, dict) and isinstance(observation.get("result"), dict)
    ]

    return {
        "continuation_id": next((value for value in continuation_ids if value), None),
        "answer": result.answer,
        "tool_calls": result.tool_calls,
        "observations": result.observations,
        "completed": result.completed,
    }


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
