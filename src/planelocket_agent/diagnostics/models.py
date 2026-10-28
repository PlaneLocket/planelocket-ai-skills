"""Platform-independent diagnostic result models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryUsage:
    """Normalized system memory measurements."""

    total_bytes: int
    available_bytes: int
    used_bytes: int
    used_percent: float
    swap_total_bytes: int
    swap_used_bytes: int


@dataclass(frozen=True)
class DiskUsage:
    """Normalized filesystem capacity measurements."""

    mount_point: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    used_percent: float
