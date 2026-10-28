"""Record investigation evidence in persistent memory."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from planelocket_agent.memory.models import MemoryKind, MemoryRecord
from planelocket_agent.memory.storage import MemoryStorage


class MemoryRecorder:
    """Persist observations without promoting them to verified facts."""

    def __init__(self, storage: MemoryStorage):
        self.storage = storage

    def record_observation(
        self,
        observation: dict,
        investigation_id: str,
    ) -> MemoryRecord:
        """Persist a tool observation and return its memory record."""

        record = MemoryRecord(
            id=str(uuid4()),
            kind=MemoryKind.OBSERVATION,
            content=json.dumps(observation, sort_keys=True),
            source=str(observation.get("tool", "unknown")),
            created_at=datetime.now(UTC),
            investigation_id=investigation_id,
        )

        self.storage.save(record)

        return record
