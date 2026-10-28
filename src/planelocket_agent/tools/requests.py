"""Validation of model-proposed diagnostic tool requests."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolRequest:
    """Validated collection of approved diagnostic tool names."""

    tools: tuple[str, ...]


def validate_tool_request(
    payload: Any,
    allowed_tools: Collection[str],
    max_tools: int = 4,
) -> ToolRequest:
    """Validate a proposed tool request without executing anything."""

    if not isinstance(payload, dict):
        raise ValueError("Tool request must be a JSON object")

    if set(payload) != {"tools"}:
        raise ValueError("Tool request must contain only the 'tools' field")

    proposed = payload["tools"]

    if not isinstance(proposed, list):
        raise ValueError("'tools' must be a list")

    if not 0 < max_tools:
        raise ValueError("max_tools must be positive")

    if len(proposed) > max_tools:
        raise ValueError(f"Tool request exceeds maximum of {max_tools}")

    allowed = set(allowed_tools)
    validated = []

    for name in proposed:
        if not isinstance(name, str):
            raise ValueError("Tool names must be strings")

        if name not in allowed:
            raise ValueError(f"Unknown or unauthorized tool: {name}")

        if name in validated:
            raise ValueError(f"Duplicate tool request: {name}")

        validated.append(name)

    return ToolRequest(tools=tuple(validated))
