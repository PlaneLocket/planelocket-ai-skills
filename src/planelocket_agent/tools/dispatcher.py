"""Allowlisted diagnostic tool dispatcher."""

from dataclasses import asdict
from typing import Any

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)
from planelocket_agent.integrations.emby import (
    get_episodes,
    get_seasons,
    search_movies,
    search_series,
)
from planelocket_agent.memory.recorder import MemoryRecorder
from planelocket_agent.tools.definitions import (
    ToolArgument,
    ToolDefinition,
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
            "search_movies": ToolDefinition(
                name="search_movies",
                description=(
                    "Search the Emby movie library for candidate titles. "
                    "Results may include partial matches and do not establish "
                    "that a requested title is present."
                ),
                handler=search_movies,
                arguments={
                    "title": "Required string. Movie title or search phrase.",
                },
            ),
            "search_series": ToolDefinition(
                name="search_series",
                description=(
                    "Search the Emby television library for candidate series titles. "
                    "Results may include partial matches and do not establish "
                    "that a requested series is present."
                ),
                handler=search_series,
                arguments={
                    "title": "Required string. Television series title or search phrase.",
                },
            ),
            "get_seasons": ToolDefinition(
                name="get_seasons",
                description=(
                    "List available seasons of an Emby television series. "
                    "Requires a series ID obtained from search_series."
                ),
                handler=get_seasons,
                arguments={
                    "series_id": "Required string. Emby television series ID.",
                },
            ),
            "get_episodes": ToolDefinition(
                name="get_episodes",
                description=(
                    "List available episodes in a specific Emby television season. "
                    "Requires series and season IDs obtained from previous searches."
                ),
                handler=get_episodes,
                arguments={
                    "series_id": "Required string. Emby television series ID.",
                    "season_id": "Required string. Emby season ID.",
                },
            ),
        }

        self._knowledge = None

        if knowledge is not None:
            self.bind_knowledge(knowledge)

    def bind_knowledge(self, knowledge: KnowledgeProvider) -> None:
        """Register knowledge tools without replacing existing tools."""

        self._knowledge = knowledge

        self._definitions["list_references"] = ToolDefinition(
            name="list_references",
            description=(
                "List knowledge reference documents available for the selected Skill."
            ),
            handler=knowledge.list_references,
        )

        self._definitions["read_reference"] = ToolDefinition(
            name="read_reference",
            description=("Read a knowledge reference document for the selected Skill."),
            handler=knowledge.read_reference,
            arguments={
                "filename": (
                    "Required string. Must be a filename returned by list_references."
                ),
            },
        )

    def bind_memory(self, memory: MemoryRecorder) -> None:
        """Register read-only historical evidence retrieval."""

        self._memory = memory

        self._definitions["get_investigation_history"] = ToolDefinition(
            name="get_investigation_history",
            description=(
                "Retrieve recorded observations from a previous investigation "
                "using its investigation ID. Returns historical evidence, "
                "not necessarily current system state."
            ),
            handler=self._get_investigation_history,
            arguments={
                "investigation_id": (
                    "Required string. Identifier of the investigation to retrieve."
                ),
            },
        )

    def unbind_memory(self) -> None:
        """Remove historical-memory access from this dispatcher."""

        self._definitions.pop("get_investigation_history", None)
        self._memory = None

    def _get_investigation_history(
        self,
        investigation_id: str,
    ) -> list[dict[str, Any]]:
        """Return historical records with timestamps and provenance."""

        records = self._memory.get_investigation_history(investigation_id)

        return [
            {
                "id": record.id,
                "kind": record.kind.value,
                "content": record.content,
                "source": record.source,
                "created_at": record.created_at.isoformat(),
                "investigation_id": record.investigation_id,
            }
            for record in records
        ]

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
        required_arguments = {
            name
            for name, specification in definition.arguments.items()
            if not isinstance(specification, ToolArgument) or specification.required
        }

        allowed_arguments = set(definition.arguments)
        received_arguments = set(arguments)

        missing = required_arguments - received_arguments
        unexpected = received_arguments - allowed_arguments

        if missing or unexpected:
            if not allowed_arguments:
                raise ValueError(f"Tool {tool_name} does not accept arguments")

            raise ValueError(
                f"Tool {tool_name} has invalid arguments. "
                f"Missing: {sorted(missing)}. "
                f"Unexpected: {sorted(unexpected)}"
            )

        for name, value in arguments.items():
            specification = definition.arguments[name]

            if isinstance(specification, ToolArgument):
                expected_type = specification.value_type
                allow_empty = specification.allow_empty
            else:
                expected_type = str
                allow_empty = False

            # bool is a subclass of int in Python, but should not
            # satisfy an integer parameter contract.
            if expected_type is int:
                valid_type = type(value) is int
            else:
                valid_type = isinstance(value, expected_type)

            if not valid_type:
                raise ValueError(f"{name} must be of type {expected_type.__name__}")

            if isinstance(value, str) and not allow_empty and not value:
                raise ValueError(f"{name} must be a nonempty string")
        result = definition.handler(**arguments)

        if hasattr(result, "__dataclass_fields__"):
            result = asdict(result)

        return {
            "tool": tool_name,
            "result": result,
        }
