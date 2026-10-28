"""Tests for memory data models."""

import unittest
from datetime import UTC, datetime, timedelta, timezone

from planelocket_agent.memory.models import MemoryKind, MemoryRecord


class TestMemoryModels(unittest.TestCase):
    def test_observation_record(self):
        timestamp = datetime(2026, 10, 28, tzinfo=UTC)

        record = MemoryRecord(
            id="observation-001",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=timestamp,
            investigation_id="investigation-001",
        )

        self.assertEqual(record.kind, MemoryKind.OBSERVATION)
        self.assertEqual(record.source, "get_resource_pressure")
        self.assertEqual(record.created_at, timestamp)
        self.assertEqual(record.investigation_id, "investigation-001")

    def test_interpretation_is_distinct_from_verified_fact(self):
        record = MemoryRecord(
            id="interpretation-001",
            kind=MemoryKind.INTERPRETATION,
            content="No significant recent CPU contention.",
            source="qwen3.5:9b",
            created_at=datetime.now(UTC),
        )

        self.assertEqual(record.kind, MemoryKind.INTERPRETATION)
        self.assertNotEqual(record.kind, MemoryKind.VERIFIED_FACT)
        self.assertIsNone(record.investigation_id)

    def test_rejects_naive_timestamp(self):
        with self.assertRaisesRegex(
            ValueError,
            "created_at must be timezone-aware",
        ):
            MemoryRecord(
                id="observation-002",
                kind=MemoryKind.OBSERVATION,
                content="Memory available: 58 GB",
                source="get_memory_usage",
                created_at=datetime(2026, 10, 28, 12, 0),
            )

    def test_normalizes_timestamp_to_utc(self):

        central = timezone(timedelta(hours=-5))

        record = MemoryRecord(
            id="observation-003",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=datetime(2026, 10, 28, 8, 0, tzinfo=central),
        )

        self.assertEqual(
            record.created_at,
            datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
        )
        self.assertEqual(record.created_at.tzinfo, UTC)


if __name__ == "__main__":
    unittest.main()
