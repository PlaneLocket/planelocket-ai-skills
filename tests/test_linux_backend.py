"""Tests for the Linux diagnostics backend."""

import unittest
from unittest.mock import patch

from planelocket_agent.diagnostics.interfaces import (
    SystemDiagnostics,
)
from planelocket_agent.diagnostics.linux.backend import (
    LinuxDiagnostics,
)
from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
)


class TestLinuxDiagnostics(unittest.TestCase):
    def setUp(self):
        self.backend = LinuxDiagnostics()

    def test_implements_diagnostic_protocol(self):
        self.assertIsInstance(
            self.backend,
            SystemDiagnostics,
        )

    @patch("planelocket_agent.diagnostics.linux.backend.get_memory_usage")
    def test_memory_delegation(self, mock_memory):
        expected = MemoryUsage(
            total_bytes=8589934592,
            available_bytes=6442450944,
            used_bytes=2147483648,
            used_percent=25.0,
            swap_total_bytes=0,
            swap_used_bytes=0,
        )

        mock_memory.return_value = expected

        result = self.backend.get_memory_usage()

        self.assertEqual(result, expected)
        mock_memory.assert_called_once_with()

    @patch("planelocket_agent.diagnostics.linux.backend.get_disk_usage")
    def test_disk_delegation(self, mock_disk):
        expected = DiskUsage(
            mount_point="/",
            total_bytes=107374182400,
            used_bytes=21474836480,
            free_bytes=85899345920,
            used_percent=20.0,
        )

        mock_disk.return_value = expected

        result = self.backend.get_disk_usage()

        self.assertEqual(result, expected)
        mock_disk.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
