"""Tests for SQLite memory persistence."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from planelocket_agent.memory.models import MemoryKind, MemoryRecord
from planelocket_agent.memory.storage import (
    SCHEMA_VERSION,
    MemoryStorage,
)


class TestMemoryStorage(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

        self.database_path = Path(self.temporary.name) / "memory.sqlite3"

        self.storage = MemoryStorage(self.database_path)

    def test_initializes_database(self):
        self.storage.initialize()

        self.assertTrue(self.database_path.is_file())

        with closing(sqlite3.connect(self.database_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION)

    def test_initialization_is_idempotent(self):
        self.storage.initialize()
        self.storage.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION)

    def test_rejects_newer_schema(self):
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")

        with self.assertRaisesRegex(
            RuntimeError,
            "newer than supported",
        ):
            self.storage.initialize()

    def test_creates_memory_records_table(self):
        self.storage.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }

        self.assertIn("memory_records", tables)

    def test_memory_records_schema(self):
        self.storage.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(memory_records)")
            }

        self.assertEqual(
            columns,
            {
                "id",
                "kind",
                "content",
                "source",
                "created_at",
                "investigation_id",
            },
        )

    def test_repairs_version_one_database_without_table(self):
        """Support databases created before memory_records existed."""

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        self.storage.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection:
            table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'memory_records'
                """
            ).fetchone()

            version = connection.execute("PRAGMA user_version").fetchone()[0]

        self.assertIsNotNone(table)
        self.assertEqual(version, SCHEMA_VERSION)

    def test_saves_memory_record(self):
        self.storage.initialize()

        record = MemoryRecord(
            id="observation-001",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
            investigation_id="investigation-001",
        )

        self.storage.save(record)

        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT id, kind, content, source,
                       created_at, investigation_id
                FROM memory_records
                WHERE id = ?
                """,
                (record.id,),
            ).fetchone()

        self.assertEqual(
            row,
            (
                "observation-001",
                "observation",
                "CPU PSI avg10: 0.00",
                "get_resource_pressure",
                "2026-10-28T13:00:00+00:00",
                "investigation-001",
            ),
        )

    def test_rejects_duplicate_memory_record(self):
        self.storage.initialize()

        record = MemoryRecord(
            id="observation-001",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
        )

        self.storage.save(record)

        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.save(record)

        with closing(sqlite3.connect(self.database_path)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM memory_records"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_retrieves_memory_record(self):
        self.storage.initialize()

        original = MemoryRecord(
            id="observation-001",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
            investigation_id="investigation-001",
        )

        self.storage.save(original)

        retrieved = self.storage.get(original.id)

        self.assertEqual(retrieved, original)
        self.assertIsInstance(retrieved, MemoryRecord)
        self.assertIsInstance(retrieved.kind, MemoryKind)

    def test_returns_none_for_missing_record(self):
        self.storage.initialize()

        result = self.storage.get("does-not-exist")

        self.assertIsNone(result)

    def test_retrieves_records_by_investigation(self):
        self.storage.initialize()

        first = MemoryRecord(
            id="observation-001",
            kind=MemoryKind.OBSERVATION,
            content="CPU PSI avg10: 0.00",
            source="get_resource_pressure",
            created_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC),
            investigation_id="investigation-001",
        )

        second = MemoryRecord(
            id="interpretation-001",
            kind=MemoryKind.INTERPRETATION,
            content="No significant recent CPU contention.",
            source="qwen3.5:9b",
            created_at=datetime(2026, 10, 28, 13, 1, tzinfo=UTC),
            investigation_id="investigation-001",
        )

        unrelated = MemoryRecord(
            id="observation-002",
            kind=MemoryKind.OBSERVATION,
            content="Swap usage: 0 bytes",
            source="get_memory_usage",
            created_at=datetime(2026, 10, 28, 13, 2, tzinfo=UTC),
            investigation_id="investigation-002",
        )

        # Insert out of chronological order.
        for record in (second, unrelated, first):
            self.storage.save(record)

        results = self.storage.get_by_investigation("investigation-001")

        self.assertEqual(results, [first, second])

    def test_returns_empty_history_for_unknown_investigation(self):
        self.storage.initialize()

        results = self.storage.get_by_investigation("does-not-exist")

        self.assertEqual(results, [])

    def test_creates_investigation_index(self):
        self.storage.initialize()

        with closing(sqlite3.connect(self.database_path)) as connection:
            indexes = {
                row[1]
                for row in connection.execute("PRAGMA index_list(memory_records)")
            }

        self.assertIn(
            "idx_memory_records_investigation",
            indexes,
        )


if __name__ == "__main__":
    unittest.main()
