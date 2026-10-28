"""Allowlisted diagnostic tool dispatcher."""

from dataclasses import asdict
from typing import Any

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)


class ToolDispatcher:
    """Execute explicitly approved diagnostic capabilities."""

    def __init__(self, backend: SystemDiagnostics):
        self._backend = backend

        self._tools = {
            "get_memory_usage": backend.get_memory_usage,
            "get_disk_usage": backend.get_disk_usage,
        }

    def available_tools(self) -> tuple[str, ...]:
        """Return the names of approved tools."""
        return tuple(self._tools)

    def execute(self, tool_name: str) -> dict[str, Any]:
        """Execute an approved tool and return structured data."""

        if tool_name not in self._tools:
            raise ValueError(f"Unknown or unauthorized tool: {tool_name}")

        result = self._tools[tool_name]()

        return {
            "tool": tool_name,
            "result": asdict(result),
        }
