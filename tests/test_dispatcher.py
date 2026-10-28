"""Tests for the authorized diagnostic tool dispatcher."""

import unittest

from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
)
from planelocket_agent.tools.dispatcher import ToolDispatcher


class FakeDiagnostics:
    """A diagnostic backend that does not access the OS."""

    def __init__(self):
        self.memory_calls = 0
        self.disk_calls = 0

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


class TestToolDispatcher(unittest.TestCase):
    def setUp(self):
        self.backend = FakeDiagnostics()
        self.dispatcher = ToolDispatcher(self.backend)

    def test_available_tools(self):
        self.assertEqual(
            self.dispatcher.available_tools(),
            ("get_memory_usage", "get_disk_usage"),
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

        self.dispatcher._tools["get_memory_usage"] = failing_memory

        with self.assertRaisesRegex(
            RuntimeError,
            "Diagnostic collection failed",
        ):
            self.dispatcher.execute("get_memory_usage")


if __name__ == "__main__":
    unittest.main()
