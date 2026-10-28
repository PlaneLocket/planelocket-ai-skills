"""Tests for investigation observation recording."""

import tempfile
import unittest
from pathlib import Path

from planelocket_agent.memory.models import MemoryKind
from planelocket_agent.memory.recorder import MemoryRecorder
from planelocket_agent.memory.storage import MemoryStorage


class TestMemoryRecorder(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

        database_path = Path(self.temporary_directory.name) / "memory.sqlite3"

        self.storage = MemoryStorage(database_path)
        self.storage.initialize()
        self.recorder = MemoryRecorder(self.storage)

    def test_records_tool_observation(self):
        observation = {
            "tool": "get_memory_usage",
            "available_bytes": 8589934592,
        }

        record = self.recorder.record_observation(
            observation,
            investigation_id="investigation-001",
        )

        self.assertEqual(record.kind, MemoryKind.OBSERVATION)
        self.assertEqual(record.source, "get_memory_usage")
        self.assertEqual(
            record.investigation_id,
            "investigation-001",
        )

        self.assertEqual(self.storage.get(record.id), record)

    def test_observation_is_not_verified_fact(self):
        observation = {
            "tool": "get_resource_pressure",
            "interpretation": "The system is healthy.",
        }

        record = self.recorder.record_observation(
            observation,
            investigation_id="investigation-002",
        )

        self.assertEqual(record.kind, MemoryKind.OBSERVATION)
        self.assertNotEqual(
            record.kind,
            MemoryKind.VERIFIED_FACT,
        )


if __name__ == "__main__":
    unittest.main()
