"""Structured metadata for agent tools."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """Describe an authorized tool and its invocation contract."""

    name: str
    description: str
    handler: Callable[..., Any]
    arguments: dict[str, str] = field(default_factory=dict)

    def model_description(self) -> dict[str, Any]:
        """Return the information exposed to the language model."""
        return {
            "description": self.description,
            "arguments": dict(self.arguments),
        }
