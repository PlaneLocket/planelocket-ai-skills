"""Validate decisions made by the reasoning agent."""

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class AgentDecision:
    """A validated agent decision."""

    action: Literal["tool", "finish"]
    tool: str | None
    answer: str | None


def validate_agent_decision(
    payload: Any,
    allowed_tools: tuple[str, ...],
) -> AgentDecision:
    """Validate an agent decision without executing anything."""

    if not isinstance(payload, dict):
        raise ValueError("Agent decision must be a JSON object")

    if set(payload) != {"action", "tool", "answer"}:
        raise ValueError(
            "Agent decision must contain exactly 'action', 'tool', and 'answer'"
        )

    action = payload["action"]
    tool = payload["tool"]
    answer = payload["answer"]

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

    else:
        raise ValueError(f"Unknown agent action: {action}")

    return AgentDecision(
        action=action,
        tool=tool,
        answer=answer.strip() if isinstance(answer, str) else None,
    )
