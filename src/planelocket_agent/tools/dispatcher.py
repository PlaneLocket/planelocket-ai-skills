"""Allowlisted diagnostic tool dispatcher."""

from dataclasses import asdict
from typing import Any

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)
from planelocket_agent.tools.knowledge import KnowledgeProvider


class ToolDispatcher:
    """Execute explicitly approved diagnostic capabilities."""

    def __init__(
        self,
        backend: SystemDiagnostics,
        knowledge: KnowledgeProvider | None = None,
    ):
        self._backend = backend

        self._tools = {
            "get_memory_usage": backend.get_memory_usage,
            "get_disk_usage": backend.get_disk_usage,
            "get_resource_pressure": backend.get_resource_pressure,
        }

        self._knowledge = knowledge

        if knowledge is not None:
            self._tools["list_references"] = knowledge.list_references
            self._tools["read_reference"] = knowledge.read_reference

    def available_tools(self) -> tuple[str, ...]:
        """Return the names of approved tools."""
        return tuple(self._tools)

    def execute(
        self,
        tool_name: str,
        **arguments: Any,
    ) -> dict[str, Any]:
        """Execute an authorized tool with validated arguments."""

        if tool_name not in self._tools:
            raise ValueError(f"Unknown or unauthorized tool: {tool_name}")

        if tool_name == "read_reference":
            if set(arguments) != {"filename"}:
                raise ValueError(
                    # "read_reference requires exactly one argument: filename"
                    "read_reference requires exactly one argument: filename. "
                    f"Received argument keys: {sorted(arguments)}"
                )

            filename = arguments["filename"]

            if not isinstance(filename, str) or not filename:
                raise ValueError("filename must be a nonempty string")

            result = self._tools[tool_name](filename=filename)

        else:
            if arguments:
                raise ValueError(f"Tool {tool_name} does not accept arguments")

            result = self._tools[tool_name]()

        if hasattr(result, "__dataclass_fields__"):
            result = asdict(result)

        return {
            "tool": tool_name,
            "result": result,
        }
