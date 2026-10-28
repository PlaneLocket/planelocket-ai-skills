"""Structured metadata for agent tools."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolArgument:
    """Describe a tool parameter and its validation requirements."""

    description: str
    value_type: type = str
    required: bool = True
    allow_empty: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    """Describe an authorized tool and its invocation contract."""

    name: str
    description: str
    handler: Callable[..., Any]
    arguments: dict[str, str | ToolArgument] = field(default_factory=dict)

    def model_description(self) -> dict[str, Any]:
        """Return the information exposed to the language model."""

        descriptions = {}

        for name, argument in self.arguments.items():
            if isinstance(argument, ToolArgument):
                descriptions[name] = {
                    "description": argument.description,
                    "type": argument.value_type.__name__,
                    "required": argument.required,
                }
            else:
                descriptions[name] = argument

        return {
            "description": self.description,
            "arguments": descriptions,
        }
