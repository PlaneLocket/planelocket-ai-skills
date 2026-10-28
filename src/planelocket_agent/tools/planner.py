"""Model-assisted selection of approved diagnostic tools."""

import json

from planelocket_agent.ollama import OllamaClient
from planelocket_agent.tools.requests import (
    ToolRequest,
    validate_tool_request,
)


class ToolPlanner:
    """Ask a model to propose approved diagnostic operations."""

    def __init__(
        self,
        client: OllamaClient,
        allowed_tools: tuple[str, ...],
        max_tools: int = 4,
    ):
        self.client = client
        self.allowed_tools = allowed_tools
        self.max_tools = max_tools

    def plan(
        self,
        user_request: str,
        skill_instructions: str,
    ) -> ToolRequest:
        """Return a validated diagnostic tool request."""

        schema = {
            "type": "object",
            "properties": {
                "tools": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": list(self.allowed_tools),
                    },
                    "maxItems": self.max_tools,
                    "uniqueItems": True,
                }
            },
            "required": ["tools"],
            "additionalProperties": False,
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a diagnostic tool planner. "
                    "Select only the tools needed to answer "
                    "the user's request. "
                    "Do not invent tools. "
                    "Do not execute commands. "
                    "Return only the requested JSON structure."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request:\n{user_request}\n\n"
                    f"Skill instructions:\n{skill_instructions}\n\n"
                    f"Available tools:\n"
                    f"{json.dumps(self.allowed_tools)}"
                ),
            },
        ]

        response = self.client.chat(
            messages,
            response_format=schema,
            options={"temperature": 0},
        )

        try:
            payload = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError("Model returned invalid tool-request JSON") from exc

        return validate_tool_request(
            payload,
            self.allowed_tools,
            max_tools=self.max_tools,
        )
