"""Tests for normalized Linux disk diagnostics."""

import tempfile
import unittest
from pathlib import Path
from collections import namedtuple

DiskUsageResult = namedtuple(
    "DiskUsageResult",
    ["total", "used", "free"],
)
from unittest.mock import patch

from planelocket_agent.diagnostics.models import DiskUsage
from planelocket_agent.diagnostics.linux.disk import get_disk_usage


class TestLinuxDisk(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.mount_point = Path(self.temporary.name)

    def test_normalized_disk_values(self):
        total = 100 * 1024**3
        used = 25 * 1024**3
        free = 70 * 1024**3

        with (
            patch(
                "planelocket_agent.diagnostics.linux.disk.os.path.ismount",
                return_value=True,
            ),
            patch(
                "planelocket_agent.diagnostics.linux.disk.shutil.disk_usage",
                return_value=DiskUsageResult(total, used, free),
            ),
        ):
            result = get_disk_usage(self.mount_point)

        self.assertIsInstance(result, DiskUsage)
        self.assertEqual(result.total_bytes, total)
        self.assertEqual(result.used_bytes, used)
        self.assertEqual(result.free_bytes, free)
        self.assertEqual(result.used_percent, 25.0)
        self.assertEqual(
            result.mount_point,
            str(self.mount_point.resolve()),
        )

    def test_nonexistent_path(self):
        missing = self.mount_point / "missing"

        with self.assertRaises(FileNotFoundError):
            get_disk_usage(missing)

    def test_regular_file_rejected(self):
        file_path = self.mount_point / "file.txt"
        file_path.write_text("test", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "not a directory"):
            get_disk_usage(file_path)

    def test_non_mount_point_rejected(self):
        with patch(
            "planelocket_agent.diagnostics.linux.disk.os.path.ismount",
            return_value=False,
        ):
            with self.assertRaisesRegex(ValueError, "not a mount point"):
                get_disk_usage(self.mount_point)

    def test_zero_capacity_rejected(self):
        with (
            patch(
                "planelocket_agent.diagnostics.linux.disk.os.path.ismount",
                return_value=True,
            ),
            patch(
                "planelocket_agent.diagnostics.linux.disk.shutil.disk_usage",
                return_value=DiskUsageResult(0, 0, 0),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Invalid filesystem capacity"):
                get_disk_usage(self.mount_point)


if __name__ == "__main__":
    unittest.main()
