"""SQLite persistence for PlaneLocket AI memory."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from planelocket_agent.memory.models import MemoryKind, MemoryRecord

SCHEMA_VERSION = 1


class MemoryStorage:
    """Manage the lifecycle of the agent's SQLite database."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        """Initialize or migrate the memory database."""

        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            version = connection.execute("PRAGMA user_version").fetchone()[0]

            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer "
                    f"than supported version {SCHEMA_VERSION}"
                )

            if version <= SCHEMA_VERSION:
                connection.execute(
                    """
                        CREATE TABLE IF NOT EXISTS memory_records (
                            id TEXT PRIMARY KEY,
                            kind TEXT NOT NULL CHECK (
                                kind IN (
                                    'observation',
                                    'verified_fact',
                                    'interpretation'
                                )
                            ),
                            content TEXT NOT NULL,
                            source TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            investigation_id TEXT
                        )
                        """
                )
                connection.execute(
                    """
                        CREATE INDEX IF NOT EXISTS
                            idx_memory_records_investigation
                        ON memory_records (
                            investigation_id,
                            created_at,
                            id
                        )
                        """
                )
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save(self, record: MemoryRecord) -> None:
        """Persist a memory record without overwriting existing records."""

        with (
            closing(sqlite3.connect(self.database_path)) as connection,
            connection,
        ):
            connection.execute(
                """
                    INSERT INTO memory_records (
                        id,
                        kind,
                        content,
                        source,
                        created_at,
                        investigation_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                (
                    record.id,
                    record.kind.value,
                    record.content,
                    record.source,
                    record.created_at.isoformat(),
                    record.investigation_id,
                ),
            )

    def get(self, record_id: str) -> MemoryRecord | None:
        """Retrieve a memory record by ID."""

        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT id, kind, content, source,
                       created_at, investigation_id
                FROM memory_records
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()

        if row is None:
            return None

        return self._record_from_row(row)

    def get_by_investigation(
        self,
        investigation_id: str,
    ) -> list[MemoryRecord]:
        """Retrieve investigation records in chronological order."""

        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute(
                """
                SELECT id, kind, content, source,
                       created_at, investigation_id
                FROM memory_records
                WHERE investigation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (investigation_id,),
            ).fetchall()

        return [self._record_from_row(row) for row in rows]

    @staticmethod
    def _record_from_row(row: tuple) -> MemoryRecord:
        """Convert a SQLite result row into a memory record."""

        return MemoryRecord(
            id=row[0],
            kind=MemoryKind(row[1]),
            content=row[2],
            source=row[3],
            created_at=datetime.fromisoformat(row[4]),
            investigation_id=row[5],
        )
