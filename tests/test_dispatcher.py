"""Tests for the authorized diagnostic tool dispatcher."""

import unittest
from datetime import UTC, datetime

from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
    PressureSample,
    ResourcePressure,
)
from planelocket_agent.memory.models import MemoryKind, MemoryRecord
from planelocket_agent.tools.definitions import (
    ToolArgument,
    ToolDefinition,
)
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
                "search_books",
                "get_memory_usage",
                "get_disk_usage",
                "get_resource_pressure",
                "search_movies",
                "search_people",
                "get_person_movies",
                "search_series",
                "get_seasons",
                "get_episodes",
                "search_artists",
                "get_artist_tracks",
                "get_artist_albums",
                "get_album_tracks",
                "search_inventory_parts",
                "get_inventory_stock",
                "search_media",
                "get_media_details",
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
                "arguments": {"filename": "example.md"},
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
                "arguments": {},
                "result": {"status": "ok"},
            },
        )

    def test_typed_optional_arguments(self):
        calls = []

        def search_handler(query, limit=10):
            calls.append((query, limit))
            return {"query": query, "limit": limit}

        definition = ToolDefinition(
            name="search_example",
            description="Search example records.",
            handler=search_handler,
            arguments={
                "query": ToolArgument(
                    description="Search query.",
                ),
                "limit": ToolArgument(
                    description="Maximum results.",
                    value_type=int,
                    required=False,
                ),
            },
        )

        self.dispatcher._definitions["search_example"] = definition

        # Optional argument omitted: handler uses its default.
        result = self.dispatcher.execute(
            "search_example",
            query="pressure",
        )

        self.assertEqual(
            result["result"],
            {"query": "pressure", "limit": 10},
        )

        # Explicit integer argument.
        result = self.dispatcher.execute(
            "search_example",
            query="pressure",
            limit=5,
        )

        self.assertEqual(result["result"]["limit"], 5)

        # Reject boolean values masquerading as integers.
        with self.assertRaises(ValueError):
            self.dispatcher.execute(
                "search_example",
                query="pressure",
                limit=True,
            )

        # Reject incorrectly typed arguments.
        with self.assertRaises(ValueError):
            self.dispatcher.execute(
                "search_example",
                query=123,
            )

        # Reject missing required arguments.
        with self.assertRaises(ValueError):
            self.dispatcher.execute(
                "search_example",
                limit=5,
            )

        # Reject unexpected arguments.
        with self.assertRaises(ValueError):
            self.dispatcher.execute(
                "search_example",
                query="pressure",
                command="whoami",
            )

        # Only valid requests should reach the handler.
        self.assertEqual(
            calls,
            [
                ("pressure", 10),
                ("pressure", 5),
            ],
        )

    def test_register_preserves_existing_tools(self):
        def custom_handler():
            return {"status": "available"}

        definition = ToolDefinition(
            name="custom_tool",
            description="A custom registered capability.",
            handler=custom_handler,
        )

        self.dispatcher._definitions["custom_tool"] = definition

        self.assertIn(
            "custom_tool",
            self.dispatcher.available_tools(),
        )

        self.assertEqual(
            self.dispatcher.execute("custom_tool")["result"],
            {"status": "available"},
        )

    def test_bind_knowledge_preserves_existing_tools(self):
        class FakeKnowledge:
            def list_references(self):
                return ("pressure-stall-information.md",)

            def read_reference(self, filename):
                return f"Contents of {filename}"

        def custom_handler():
            return {"status": "available"}

        self.dispatcher._definitions["custom_tool"] = ToolDefinition(
            name="custom_tool",
            description="A custom registered capability.",
            handler=custom_handler,
        )

        original_tools = set(self.dispatcher.available_tools())

        self.dispatcher.bind_knowledge(FakeKnowledge())

        self.assertTrue(original_tools.issubset(set(self.dispatcher.available_tools())))

        self.assertEqual(
            self.dispatcher.execute("custom_tool")["result"],
            {"status": "available"},
        )

        self.assertEqual(
            self.dispatcher.execute("list_references")["result"],
            ("pressure-stall-information.md",),
        )

        self.assertEqual(
            self.dispatcher.execute(
                "read_reference",
                filename="pressure-stall-information.md",
            )["result"],
            "Contents of pressure-stall-information.md",
        )

    def test_bind_memory_retrieves_investigation_history(self):
        """Historical evidence is accessible through the dispatcher."""

        class FakeMemory:
            def get_investigation_history(self, investigation_id):
                return [
                    MemoryRecord(
                        id="record-001",
                        kind=MemoryKind.OBSERVATION,
                        content='{"tool": "get_memory_usage"}',
                        source="get_memory_usage",
                        created_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
                        investigation_id=investigation_id,
                    )
                ]

        self.dispatcher.bind_memory(FakeMemory())

        self.assertIn(
            "get_investigation_history",
            self.dispatcher.available_tools(),
        )

        response = self.dispatcher.execute(
            "get_investigation_history",
            investigation_id="investigation-001",
        )

        self.assertEqual(
            response["result"],
            [
                {
                    "id": "record-001",
                    "kind": "observation",
                    "content": '{"tool": "get_memory_usage"}',
                    "source": "get_memory_usage",
                    "created_at": "2026-10-28T12:00:00+00:00",
                    "investigation_id": "investigation-001",
                }
            ],
        )

    def test_memory_tool_validates_arguments_and_preserves_tools(self):
        """Memory retrieval must obey dispatcher argument validation."""

        class FakeMemory:
            def __init__(self):
                self.calls = []

            def get_investigation_history(self, investigation_id):
                self.calls.append(investigation_id)
                return []

        memory = FakeMemory()

        original_tools = set(self.dispatcher.available_tools())

        self.dispatcher.bind_memory(memory)

        # Existing diagnostic tools remain available.
        self.assertTrue(original_tools.issubset(set(self.dispatcher.available_tools())))

        invalid_arguments = (
            {},
            {"investigation_id": ""},
            {"investigation_id": 123},
            {"investigation_id": "investigation-001", "command": "whoami"},
        )

        for arguments in invalid_arguments:
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(ValueError),
            ):
                self.dispatcher.execute(
                    "get_investigation_history",
                    **arguments,
                )

        # Invalid requests must never reach persistent storage.
        self.assertEqual(memory.calls, [])

        # A valid request succeeds.
        response = self.dispatcher.execute(
            "get_investigation_history",
            investigation_id="investigation-001",
        )

        self.assertEqual(response["result"], [])
        self.assertEqual(memory.calls, ["investigation-001"])


if __name__ == "__main__":
    unittest.main()
