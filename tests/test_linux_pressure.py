"""Tests for Linux Pressure Stall Information diagnostics."""

import tempfile
import unittest
from pathlib import Path

from planelocket_agent.diagnostics.linux.pressure import (
    get_resource_pressure,
)
from planelocket_agent.diagnostics.models import (
    ResourcePressure,
)


class TestLinuxPressure(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.directory = Path(self.temporary.name)

        self.write_pressure(
            "cpu",
            "some avg10=1.25 avg60=0.50 avg300=0.10 total=123456\n",
        )
        self.write_pressure(
            "memory",
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=100\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=50\n",
        )
        self.write_pressure(
            "io",
            "some avg10=2.50 avg60=1.00 avg300=0.25 total=999999\n"
            "full avg10=0.50 avg60=0.20 avg300=0.05 total=100000\n",
        )

    def write_pressure(self, resource, content):
        (self.directory / resource).write_text(
            content,
            encoding="utf-8",
        )

    def test_valid_pressure(self):
        result = get_resource_pressure(self.directory)

        self.assertIsInstance(result, ResourcePressure)
        self.assertEqual(result.cpu_some.avg10, 1.25)
        self.assertEqual(result.cpu_some.total_microseconds, 123456)
        self.assertIsNone(result.cpu_full)
        self.assertEqual(result.memory_full.total_microseconds, 50)
        self.assertEqual(result.io_some.avg60, 1.0)
        self.assertEqual(result.io_full.avg300, 0.05)

    def test_optional_cpu_full(self):
        self.write_pressure(
            "cpu",
            "some avg10=1.00 avg60=0.50 avg300=0.25 total=100\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
        )

        result = get_resource_pressure(self.directory)

        self.assertIsNotNone(result.cpu_full)
        self.assertEqual(result.cpu_full.total_microseconds, 0)

    def test_missing_some(self):
        self.write_pressure(
            "cpu",
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
        )

        with self.assertRaisesRegex(ValueError, "Missing 'some'"):
            get_resource_pressure(self.directory)

    def test_missing_required_full(self):
        self.write_pressure(
            "memory",
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=100\n",
        )

        with self.assertRaisesRegex(ValueError, "Missing required full"):
            get_resource_pressure(self.directory)

    def test_duplicate_measurement(self):
        self.write_pressure(
            "cpu",
            "some avg10=1.00 avg60=0.50 avg300=0.25 total=100\n"
            "some avg10=1.00 avg60=0.50 avg300=0.25 total=100\n",
        )

        with self.assertRaisesRegex(ValueError, "Duplicate pressure type"):
            get_resource_pressure(self.directory)

    def test_invalid_average(self):
        self.write_pressure(
            "cpu",
            "some avg10=101.00 avg60=0.50 avg300=0.25 total=100\n",
        )

        with self.assertRaisesRegex(ValueError, "out of range"):
            get_resource_pressure(self.directory)

    def test_negative_total(self):
        self.write_pressure(
            "cpu",
            "some avg10=1.00 avg60=0.50 avg300=0.25 total=-1\n",
        )

        with self.assertRaisesRegex(ValueError, "out of range"):
            get_resource_pressure(self.directory)

    def test_invalid_numeric_value(self):
        self.write_pressure(
            "cpu",
            "some avg10=invalid avg60=0.50 avg300=0.25 total=100\n",
        )

        with self.assertRaisesRegex(ValueError, "Invalid pressure values"):
            get_resource_pressure(self.directory)

    def test_missing_field(self):
        self.write_pressure(
            "cpu",
            "some avg10=1.00 avg60=0.50 total=100\n",
        )

        with self.assertRaisesRegex(ValueError, "Invalid pressure fields"):
            get_resource_pressure(self.directory)


if __name__ == "__main__":
    unittest.main()
