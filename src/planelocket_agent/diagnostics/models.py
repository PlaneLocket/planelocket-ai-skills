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


@dataclass(frozen=True)
class PressureSample:
    """Linux PSI stall measurements for one resource and stall type."""

    avg10: float
    avg60: float
    avg300: float
    total_microseconds: int


@dataclass(frozen=True)
class ResourcePressure:
    """Linux CPU, memory, and I/O pressure measurements."""

    cpu_some: PressureSample
    cpu_full: PressureSample | None
    memory_some: PressureSample
    memory_full: PressureSample
    io_some: PressureSample
    io_full: PressureSample
