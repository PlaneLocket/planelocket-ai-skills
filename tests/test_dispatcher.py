"""Tests for the authorized diagnostic tool dispatcher."""

import unittest

from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
    PressureSample,
    ResourcePressure,
)
from planelocket_agent.tools.definitions import ToolDefinition
from planelocket_agent.tools.dispatcher import ToolDispatcher


class FakeDiagnostics:
    """A diagnostic backend that does not access the OS."""

    def __init__(self):
        self.memory_calls = 0
        self.disk_calls = 0
        self.pressure_calls = 0

    def get_memory_usage(self) -> MemoryUsage:
        self.memory_calls += 1

        return MemoryUsage(
            total_bytes=8 * 1024**3,
            available_bytes=6 * 1024**3,
            used_bytes=2 * 1024**3,
            used_percent=25.0,
            swap_total_bytes=0,
            swap_used_bytes=0,
        )

    def get_disk_usage(self) -> DiskUsage:
        self.disk_calls += 1

        return DiskUsage(
            mount_point="/",
            total_bytes=100 * 1024**3,
            used_bytes=25 * 1024**3,
            free_bytes=70 * 1024**3,
            used_percent=25.0,
        )

    def get_resource_pressure(self) -> ResourcePressure:
        self.pressure_calls += 1

        sample = PressureSample(
            avg10=0.0,
            avg60=0.0,
            avg300=0.0,
            total_microseconds=100,
        )

        return ResourcePressure(
            cpu_some=sample,
            cpu_full=None,
            memory_some=sample,
            memory_full=sample,
            io_some=sample,
            io_full=sample,
        )


class TestToolDispatcher(unittest.TestCase):
    def setUp(self):
        self.backend = FakeDiagnostics()
        self.dispatcher = ToolDispatcher(self.backend)

    def test_available_tools(self):
        self.assertEqual(
            self.dispatcher.available_tools(),
            (
                "get_memory_usage",
                "get_disk_usage",
                "get_resource_pressure",
            ),
        )

    def test_memory_dispatch(self):
        response = self.dispatcher.execute("get_memory_usage")

        self.assertEqual(response["tool"], "get_memory_usage")
        self.assertEqual(
            response["result"]["used_percent"],
            25.0,
        )

        self.assertEqual(self.backend.memory_calls, 1)
        self.assertEqual(self.backend.disk_calls, 0)

    def test_disk_dispatch(self):
        response = self.dispatcher.execute("get_disk_usage")

        self.assertEqual(response["tool"], "get_disk_usage")
        self.assertEqual(
            response["result"]["mount_point"],
            "/",
        )

        self.assertEqual(self.backend.disk_calls, 1)
        self.assertEqual(self.backend.memory_calls, 0)

    def test_unauthorized_tool_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Unknown or unauthorized tool",
        ):
            self.dispatcher.execute("execute_shell_command")

        self.assertEqual(self.backend.memory_calls, 0)
        self.assertEqual(self.backend.disk_calls, 0)

    def test_empty_tool_name_rejected(self):
        with self.assertRaises(ValueError):
            self.dispatcher.execute("")

        self.assertEqual(self.backend.memory_calls, 0)
        self.assertEqual(self.backend.disk_calls, 0)

    def test_backend_failure_propagates(self):
        def failing_memory():
            raise RuntimeError("Diagnostic collection failed")

        original = self.dispatcher._definitions["get_memory_usage"]

        self.dispatcher._definitions["get_memory_usage"] = ToolDefinition(
            name=original.name,
            description=original.description,
            handler=failing_memory,
            arguments=original.arguments,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Diagnostic collection failed",
        ):
            self.dispatcher.execute("get_memory_usage")

    def test_pressure_dispatch(self):
        response = self.dispatcher.execute("get_resource_pressure")

        self.assertEqual(response["tool"], "get_resource_pressure")
        self.assertEqual(
            response["result"]["cpu_some"]["total_microseconds"],
            100,
        )

        self.assertEqual(self.backend.pressure_calls, 1)
        self.assertEqual(self.backend.memory_calls, 0)
        self.assertEqual(self.backend.disk_calls, 0)

    def test_tool_descriptions_match_available_tools(self):
        descriptions = self.dispatcher.tool_descriptions()

        self.assertEqual(
            tuple(descriptions),
            self.dispatcher.available_tools(),
        )

        self.assertEqual(
            descriptions["get_memory_usage"]["arguments"],
            {},
        )

        self.assertEqual(
            descriptions["get_resource_pressure"]["arguments"],
            {},
        )

        self.assertNotIn("read_reference", descriptions)

    def test_diagnostic_tool_rejects_arguments(self):
        with self.assertRaisesRegex(
            ValueError,
            "does not accept arguments",
        ):
            self.dispatcher.execute(
                "get_memory_usage",
                filename="unexpected.md",
            )

        self.assertEqual(self.backend.memory_calls, 0)

    def test_diagnostic_tool_rejects_unexpected_keyword(self):
        with self.assertRaisesRegex(
            ValueError,
            "does not accept arguments",
        ):
            self.dispatcher.execute(
                "get_disk_usage",
                command="whoami",
            )

        self.assertEqual(self.backend.disk_calls, 0)

    def test_tool_descriptions_match_registered_definitions(self):
        descriptions = self.dispatcher.tool_descriptions()

        self.assertEqual(
            set(descriptions),
            set(self.dispatcher.available_tools()),
        )

        for name, definition in self.dispatcher._definitions.items():
            self.assertEqual(
                descriptions[name],
                definition.model_description(),
            )

    def test_generic_tool_argument_validation(self):
        calls = []

        def example_handler(filename):
            calls.append(filename)
            return {"filename": filename}

        definition = ToolDefinition(
            name="example_tool",
            description="Example tool requiring a filename.",
            handler=example_handler,
            arguments={
                "filename": "Required filename.",
            },
        )

        self.dispatcher._definitions["example_tool"] = definition

        invalid_arguments = (
            {},
            {"filename": ""},
            {"filename": 123},
            {"filename": "example.md", "unexpected": True},
        )

        for arguments in invalid_arguments:
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(ValueError),
            ):
                self.dispatcher.execute(
                    "example_tool",
                    **arguments,
                )

        self.assertEqual(calls, [])

        result = self.dispatcher.execute(
            "example_tool",
            filename="example.md",
        )

        self.assertEqual(
            result,
            {
                "tool": "example_tool",
                "result": {"filename": "example.md"},
            },
        )

        self.assertEqual(calls, ["example.md"])

    def test_registered_tool_available_through_all_interfaces(self):
        def example_handler():
            return {"status": "ok"}

        definition = ToolDefinition(
            name="example_tool",
            description="Return an example result.",
            handler=example_handler,
        )

        self.dispatcher._definitions["example_tool"] = definition

        self.assertIn(
            "example_tool",
            self.dispatcher.available_tools(),
        )

        self.assertEqual(
            self.dispatcher.tool_descriptions()["example_tool"],
            definition.model_description(),
        )

        self.assertEqual(
            self.dispatcher.execute("example_tool"),
            {
                "tool": "example_tool",
                "result": {"status": "ok"},
            },
        )


if __name__ == "__main__":
    unittest.main()
