"""HTTP API for PlaneLocket AI."""

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from planelocket_agent.agent import PlaneLocketAgent
from planelocket_agent.config import load_config
from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.tools.dispatcher import ToolDispatcher

load_config()

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


class InvestigationRequest(BaseModel):
    """A natural-language question submitted to PlaneLocket AI."""

    question: str


@app.get("/health")
def health() -> dict[str, str]:
    """Report whether the API is running."""
    return {"status": "ok"}


@app.post("/investigate", dependencies=[Depends(require_api_token)])
def investigate(request: InvestigationRequest) -> dict:
    """Investigate a question using the PlaneLocket AI agent."""

    agent = PlaneLocketAgent(
        skills_directory=Path("skills"),
        client=OllamaClient(),
    )

    dispatcher = ToolDispatcher(LinuxDiagnostics())

    result = agent.investigate(
        request.question,
        dispatcher,
    )

    return {
        "answer": result.answer,
        "tool_calls": result.tool_calls,
        "observations": result.observations,
        "completed": result.completed,
    }
