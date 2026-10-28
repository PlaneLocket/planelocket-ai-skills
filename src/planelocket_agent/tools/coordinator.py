"""Coordinate validated diagnostic tool execution."""

from dataclasses import dataclass
from typing import Any

from planelocket_agent.tools.dispatcher import ToolDispatcher
from planelocket_agent.tools.planner import ToolPlanner
from planelocket_agent.tools.requests import validate_tool_request


@dataclass(frozen=True)
class DiagnosticExecution:
    """Results of a diagnostic execution request."""

    requested_tools: tuple[str, ...]
    results: tuple[dict[str, Any], ...]


class DiagnosticCoordinator:
    """Plan and execute an approved diagnostic request."""

    def __init__(
        self,
        planner: ToolPlanner,
        dispatcher: ToolDispatcher,
    ):
        self._planner = planner
        self._dispatcher = dispatcher

    def run(
        self,
        user_request: str,
        skill_instructions: str,
    ) -> DiagnosticExecution:
        """Plan and execute a bounded diagnostic operation."""

        proposed = self._planner.plan(
            user_request=user_request,
            skill_instructions=skill_instructions,
        )

        # Validate the complete batch at the execution boundary.
        request = validate_tool_request(
            payload={"tools": list(proposed.tools)},
            allowed_tools=self._dispatcher.available_tools(),
            max_tools=4,
        )

        results = []

        for tool_name in request.tools:
            results.append(self._dispatcher.execute(tool_name))

        return DiagnosticExecution(
            requested_tools=request.tools,
            results=tuple(results),
        )
