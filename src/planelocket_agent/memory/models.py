"""Data models for persistent agent memory."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class MemoryKind(StrEnum):
    """Categories of information retained in memory."""

    OBSERVATION = "observation"
    VERIFIED_FACT = "verified_fact"
    INTERPRETATION = "interpretation"


@dataclass(frozen=True)
class MemoryRecord:
    """An immutable memory entry with provenance."""

    id: str
    kind: MemoryKind
    content: str
    source: str
    created_at: datetime
    investigation_id: str | None = None

    def __post_init__(self) -> None:
        """Require timezone-aware timestamps and normalize to UTC."""

        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        object.__setattr__(
            self,
            "created_at",
            self.created_at.astimezone(timezone.utc),
        )
