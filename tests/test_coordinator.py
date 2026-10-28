"""Tests for diagnostic execution coordination."""

import unittest

from planelocket_agent.tools.coordinator import (
    DiagnosticCoordinator,
)
from planelocket_agent.tools.requests import ToolRequest


class FakePlanner:
    def __init__(self, tools):
        self.tools = tools
        self.calls = 0

    def plan(self, user_request, skill_instructions):
        self.calls += 1
        return ToolRequest(tools=self.tools)


class FakeDispatcher:
    def __init__(self):
        self.calls = []
        self.allowed = (
            "get_memory_usage",
            "get_disk_usage",
        )

    def available_tools(self):
        return self.allowed

    def execute(self, tool_name):
        self.calls.append(tool_name)

        return {
            "tool": tool_name,
            "result": {"status": "ok"},
        }


class TestDiagnosticCoordinator(unittest.TestCase):
    def make_coordinator(self, tools):
        planner = FakePlanner(tools)
        dispatcher = FakeDispatcher()

        coordinator = DiagnosticCoordinator(
            planner=planner,
            dispatcher=dispatcher,
        )

        return coordinator, planner, dispatcher

    def test_executes_approved_tools_in_order(self):
        coordinator, planner, dispatcher = self.make_coordinator(
            ("get_memory_usage", "get_disk_usage")
        )

        execution = coordinator.run(
            "Check system health.",
            "Use approved diagnostics.",
        )

        self.assertEqual(planner.calls, 1)

        self.assertEqual(
            dispatcher.calls,
            ["get_memory_usage", "get_disk_usage"],
        )

        self.assertEqual(
            execution.requested_tools,
            ("get_memory_usage", "get_disk_usage"),
        )

        self.assertEqual(len(execution.results), 2)

    def test_empty_request_executes_nothing(self):
        coordinator, _, dispatcher = self.make_coordinator(())

        execution = coordinator.run(
            "Explain Linux.",
            "Use tools only when needed.",
        )

        self.assertEqual(execution.requested_tools, ())
        self.assertEqual(execution.results, ())
        self.assertEqual(dispatcher.calls, [])

    def test_unauthorized_tool_rejected_before_execution(self):
        coordinator, _, dispatcher = self.make_coordinator(
            ("get_memory_usage", "execute_shell_command")
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown or unauthorized tool",
        ):
            coordinator.run(
                "Run a command.",
                "Inspect system.",
            )

        self.assertEqual(dispatcher.calls, [])

    def test_duplicate_tool_rejected_before_execution(self):
        coordinator, _, dispatcher = self.make_coordinator(
            ("get_memory_usage", "get_memory_usage")
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate tool request",
        ):
            coordinator.run(
                "Check memory twice.",
                "Inspect system.",
            )

        self.assertEqual(dispatcher.calls, [])

    def test_backend_failure_propagates(self):
        coordinator, _, dispatcher = self.make_coordinator(("get_memory_usage",))

        def failing_execute(tool_name):
            raise RuntimeError("Diagnostic backend failed")

        dispatcher.execute = failing_execute

        with self.assertRaisesRegex(
            RuntimeError,
            "Diagnostic backend failed",
        ):
            coordinator.run(
                "Check memory.",
                "Inspect system.",
            )


if __name__ == "__main__":
    unittest.main()
