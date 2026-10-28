"""Linux implementation of system diagnostics."""

from planelocket_agent.diagnostics.linux.disk import (
    get_disk_usage,
)
from planelocket_agent.diagnostics.linux.memory import (
    get_memory_usage,
)
from planelocket_agent.diagnostics.linux.pressure import (
    get_resource_pressure,
)
from planelocket_agent.diagnostics.models import (
    DiskUsage,
    MemoryUsage,
    ResourcePressure,
)


class LinuxDiagnostics:
    """Collect normalized diagnostics from the local Linux host."""

    def get_memory_usage(self) -> MemoryUsage:
        return get_memory_usage()

    def get_disk_usage(self) -> DiskUsage:
        return get_disk_usage()

    def get_resource_pressure(self) -> ResourcePressure:
        return get_resource_pressure()
