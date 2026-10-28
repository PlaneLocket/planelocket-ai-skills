"""Platform-independent diagnostic interfaces."""

from typing import Protocol, runtime_checkable

from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
    ResourcePressure,
)


@runtime_checkable
class SystemDiagnostics(Protocol):
    """Operations supported by a diagnostic backend."""

    def get_memory_usage(self) -> MemoryUsage:
        """Return normalized memory statistics."""
        ...

    def get_disk_usage(self) -> DiskUsage:
        """Return normalized filesystem statistics."""
        ...

    def get_resource_pressure(self) -> ResourcePressure:
        """Return normalized resource pressure measurements."""
        ...
