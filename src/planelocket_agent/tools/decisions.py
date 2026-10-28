"""Validate decisions made by the reasoning agent."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class AgentDecision:
    """A validated agent decision."""

    action: Literal["tool", "finish"]
    tool: str | None
    answer: str | None
    arguments: dict[str, Any] = field(default_factory=dict)


def validate_agent_decision(
    payload: Any,
    allowed_tools: tuple[str, ...],
) -> AgentDecision:
    """Validate an agent decision without executing anything."""

    if not isinstance(payload, dict):
        raise ValueError("Agent decision must be a JSON object")

    required = {"action", "tool", "answer"}
    permitted = required | {"arguments"}

    if not required.issubset(payload) or not set(payload).issubset(permitted):
        raise ValueError(
            "Agent decision must contain 'action', 'tool', and 'answer', "
            "with optional 'arguments'"
        )

    action = payload["action"]
    tool = payload["tool"]
    answer = payload["answer"]
    arguments = payload.get("arguments", {})

    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be a JSON object")

    if not all(isinstance(key, str) for key in arguments):
        raise ValueError("Tool argument names must be strings")

    if action == "tool":
        if not isinstance(tool, str) or tool not in allowed_tools:
            raise ValueError(f"Unknown or unauthorized tool: {tool}")

        if answer is not None:
            raise ValueError("Tool decisions must not include an answer")

    elif action == "finish":
        if tool is not None:
            raise ValueError("Finish decisions must not request a tool")

        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Finish decisions require a nonempty answer")

        if arguments:
            raise ValueError("Finish decisions must not include tool arguments")

    else:
        raise ValueError(f"Unknown agent action: {action}")

    return AgentDecision(
        action=action,
        tool=tool,
        answer=answer.strip() if isinstance(answer, str) else None,
        arguments=arguments.copy(),
    )
