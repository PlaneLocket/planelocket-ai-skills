"""Allowlisted diagnostic tool dispatcher."""

from dataclasses import asdict
from typing import Any

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)
from planelocket_agent.tools.definitions import ToolDefinition
from planelocket_agent.tools.knowledge import KnowledgeProvider


class ToolDispatcher:
    """Execute explicitly approved diagnostic capabilities."""

    def __init__(
        self,
        backend: SystemDiagnostics,
        knowledge: KnowledgeProvider | None = None,
    ):
        self._backend = backend

        self._definitions = {
            "get_memory_usage": ToolDefinition(
                name="get_memory_usage",
                description="Measure current system memory and swap capacity.",
                handler=backend.get_memory_usage,
            ),
            "get_disk_usage": ToolDefinition(
                name="get_disk_usage",
                description="Measure filesystem storage capacity.",
                handler=backend.get_disk_usage,
            ),
            "get_resource_pressure": ToolDefinition(
                name="get_resource_pressure",
                description=(
                    "Measure Linux CPU, memory, and I/O pressure stall information."
                ),
                handler=backend.get_resource_pressure,
            ),
        }

        self._knowledge = knowledge

        if knowledge is not None:
            self._definitions["list_references"] = ToolDefinition(
                name="list_references",
                description=(
                    "List knowledge reference documents "
                    "available for the selected Skill."
                ),
                handler=knowledge.list_references,
            )

            self._definitions["read_reference"] = ToolDefinition(
                name="read_reference",
                description=(
                    "Read a knowledge reference document for the selected Skill."
                ),
                handler=knowledge.read_reference,
                arguments={
                    "filename": (
                        "Required string. Must be a filename "
                        "returned by list_references."
                    ),
                },
            )

    def available_tools(self) -> tuple[str, ...]:
        """Return the names of approved tools."""
        return tuple(self._definitions)

    def tool_descriptions(self) -> dict[str, dict[str, Any]]:
        """Describe the tools available to the reasoning model."""

        return {
            name: definition.model_description()
            for name, definition in self._definitions.items()
        }

    def execute(
        self,
        tool_name: str,
        **arguments: Any,
    ) -> dict[str, Any]:
        """Execute an authorized tool with validated arguments."""

        if tool_name not in self._definitions:
            raise ValueError(f"Unknown or unauthorized tool: {tool_name}")

        definition = self._definitions[tool_name]
        expected_arguments = set(definition.arguments)
        received_arguments = set(arguments)

        if expected_arguments != received_arguments:
            if not expected_arguments:
                raise ValueError(f"Tool {tool_name} does not accept arguments")

            raise ValueError(
                f"Tool {tool_name} requires exactly these arguments: "
                f"{sorted(expected_arguments)}. "
                f"Received argument keys: {sorted(received_arguments)}"
            )

        for name in expected_arguments:
            value = arguments[name]

            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a nonempty string")

        result = definition.handler(**arguments)

        if hasattr(result, "__dataclass_fields__"):
            result = asdict(result)

        return {
            "tool": tool_name,
            "result": result,
        }
