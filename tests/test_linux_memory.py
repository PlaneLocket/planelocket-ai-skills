"""Tests for the normalized Linux memory backend."""

import tempfile
import unittest
from pathlib import Path

from planelocket_agent.diagnostics.models import MemoryUsage
from planelocket_agent.diagnostics.linux.memory import (
    get_memory_usage,
)


class TestLinuxMemory(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.meminfo = Path(self.temporary.name) / "meminfo"

    def write_meminfo(
        self,
        total=8388608,
        available=6291456,
        swap_total=2097152,
        swap_free=1048576,
    ):
        self.meminfo.write_text(
            f"MemTotal: {total} kB\n"
            f"MemAvailable: {available} kB\n"
            f"SwapTotal: {swap_total} kB\n"
            f"SwapFree: {swap_free} kB\n",
            encoding="utf-8",
        )

    def test_normalized_memory_values(self):
        self.write_meminfo()

        result = get_memory_usage(self.meminfo)

        self.assertIsInstance(result, MemoryUsage)
        self.assertEqual(result.total_bytes, 8 * 1024**3)
        self.assertEqual(result.available_bytes, 6 * 1024**3)
        self.assertEqual(result.used_bytes, 2 * 1024**3)
        self.assertEqual(result.used_percent, 25.0)
        self.assertEqual(result.swap_total_bytes, 2 * 1024**3)
        self.assertEqual(result.swap_used_bytes, 1 * 1024**3)

    def test_available_exceeds_total(self):
        self.write_meminfo(
            total=4194304,
            available=8388608,
        )

        with self.assertRaisesRegex(ValueError, "Invalid available memory"):
            get_memory_usage(self.meminfo)

    def test_invalid_swap_values(self):
        self.write_meminfo(
            swap_total=1048576,
            swap_free=2097152,
        )

        with self.assertRaisesRegex(ValueError, "Invalid swap memory values"):
            get_memory_usage(self.meminfo)

    def test_zero_total_memory(self):
        self.write_meminfo(total=0, available=0)

        with self.assertRaisesRegex(ValueError, "Invalid total memory"):
            get_memory_usage(self.meminfo)

    def test_no_swap(self):
        self.write_meminfo(
            swap_total=0,
            swap_free=0,
        )

        result = get_memory_usage(self.meminfo)

        self.assertEqual(result.swap_total_bytes, 0)
        self.assertEqual(result.swap_used_bytes, 0)

    def test_invalid_numeric_value(self):
        self.meminfo.write_text(
            "MemTotal: invalid kB\n"
            "MemAvailable: 6291456 kB\n"
            "SwapTotal: 0 kB\n"
            "SwapFree: 0 kB\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Invalid memory value for MemTotal"):
            get_memory_usage(self.meminfo)


if __name__ == "__main__":
    unittest.main()
