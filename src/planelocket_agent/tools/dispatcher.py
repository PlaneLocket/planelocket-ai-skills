"""Allowlisted diagnostic tool dispatcher."""

from dataclasses import asdict
from typing import Any

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)
from planelocket_agent.integrations.books import lookup_books
from planelocket_agent.integrations.emby import (
    get_album_tracks,
    get_artist_albums,
    get_artist_tracks,
    get_episodes,
    get_person_movies,
    get_seasons,
    search_artists,
    search_movies,
    search_people,
    search_series,
)
from planelocket_agent.integrations.inventree import (
    get_part_stock,
    search_parts,
)
from planelocket_agent.integrations.seerr import (
    get_media_details,
    search_media,
)
from planelocket_agent.integrations.seerr_storage import SeerrRequestStorage
from planelocket_agent.integrations.seerr_workflow import prepare_movie_request
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
            "search_books": ToolDefinition(
                name="search_books",
                description="Read-only search of owned books by title, author, or both. Returns visible records, formats and completeness; never requests acquisition.",
                handler=lookup_books,
                arguments={
                    "query": "Required string. Book title, author, or combined query."
                },
            ),
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
            "search_people": ToolDefinition(
                name="search_people",
                description=(
                    "Search Emby for people by name, including actors. "
                    "Returns matching names and Emby person IDs. "
                    "Results may include fuzzy matches."
                ),
                handler=search_people,
                arguments={
                    "name": "Required string. Person or actor name.",
                },
            ),
            "get_person_movies": ToolDefinition(
                name="get_person_movies",
                description=(
                    "List movies in the Emby library associated with a person. "
                    "Requires a person ID obtained from search_people. "
                    "Results establish a person association in Emby metadata, "
                    "but do not independently verify the person's credited role."
                ),
                handler=get_person_movies,
                arguments={
                    "person_id": "Required string. Emby person ID.",
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
            "search_artists": ToolDefinition(
                name="search_artists",
                description=(
                    "Search the Emby music library for artists by name. "
                    "Returns artist names, sorting names, and Emby artist IDs. "
                    "Results may include partial matches."
                ),
                handler=search_artists,
                arguments={
                    "name": "Required string. Artist name or search phrase.",
                },
            ),
            "get_artist_tracks": ToolDefinition(
                name="get_artist_tracks",
                description=(
                    "List tracks associated with an Emby music artist. "
                    "Requires an artist ID obtained from search_artists."
                ),
                handler=get_artist_tracks,
                arguments={
                    "artist_id": "Required string. Emby music artist ID.",
                },
            ),
            "get_artist_albums": ToolDefinition(
                name="get_artist_albums",
                description=(
                    "List albums associated with an Emby music artist. "
                    "Requires an artist ID obtained from search_artists."
                ),
                handler=get_artist_albums,
                arguments={
                    "artist_id": "Required string. Emby music artist ID.",
                },
            ),
            "get_album_tracks": ToolDefinition(
                name="get_album_tracks",
                description=(
                    "List tracks belonging to a specific Emby music album. "
                    "Requires an album ID obtained from get_artist_albums."
                ),
                handler=get_album_tracks,
                arguments={
                    "album_id": "Required string. Emby music album ID.",
                },
            ),
            "search_inventory_parts": ToolDefinition(
                name="search_inventory_parts",
                description=(
                    "Search the InvenTree inventory catalog for parts matching "
                    "a name, model number, or keyword. Returns matching part "
                    "records and their IDs. Does not establish stock availability."
                ),
                handler=search_parts,
                arguments={
                    "query": "Required string. Part name, model number, or keyword.",
                },
            ),
            "get_inventory_stock": ToolDefinition(
                name="get_inventory_stock",
                description=(
                    "Retrieve current stock records, quantities, allocations, "
                    "and storage locations for an InvenTree part. "
                    "Requires a part ID obtained from search_inventory_parts."
                ),
                handler=get_part_stock,
                arguments={
                    "part_id": ToolArgument(
                        description="InvenTree part ID returned by search_inventory_parts.",
                        value_type=int,
                    ),
                },
            ),
            "search_media": ToolDefinition(
                name="search_media",
                description=(
                    "Search Seerr for movies and television shows, including titles "
                    "not currently in the Emby library. Returns matching media "
                    "and availability information when provided by Seerr. "
                    "This tool only searches; it does not request downloads."
                ),
                handler=search_media,
                arguments={
                    "query": "Required string. Movie or television title to search for.",
                },
            ),
            "get_media_details": ToolDefinition(
                name="get_media_details",
                description=(
                    "Retrieve detailed information and Seerr media status for a "
                    "movie or television series. Requires the media type and TMDB ID "
                    "returned by search_media. This tool is read-only and does not "
                    "submit media requests."
                ),
                handler=get_media_details,
                arguments={
                    "media_type": (
                        "Required string. Either 'movie' or 'tv', "
                        "as returned by search_media."
                    ),
                    "media_id": ToolArgument(
                        description="Positive integer TMDB ID returned by search_media.",
                        value_type=int,
                    ),
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

    def bind_media_requests(self, storage: SeerrRequestStorage) -> None:
        """Register explicit movie acquisition workflow."""

        def prepare(title: str, year: int | None = None) -> dict:
            return prepare_movie_request(
                title=title,
                year=year,
                storage=storage,
            )

        self._definitions["prepare_movie_request"] = ToolDefinition(
            name="prepare_movie_request",
            description=(
                "Prepare a movie acquisition requested explicitly by the user. "
                "Requests are submitted only when automatic acquisition is enabled. "
                "Never use for general movie searches."
            ),
            handler=prepare,
            arguments={
                "title": "Required string. Exact movie title.",
                "year": ToolArgument(
                    description="Optional integer. Release year, if known.",
                    value_type=int,
                    required=False,
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
            "arguments": arguments,
            "result": result,
        }
