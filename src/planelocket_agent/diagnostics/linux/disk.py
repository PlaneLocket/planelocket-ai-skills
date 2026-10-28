"""Linux-specific filesystem utilization diagnostics."""

import os
import shutil
from pathlib import Path

from planelocket_agent.diagnostics.models import DiskUsage


def get_disk_usage(
    mount_point: Path = Path("/"),
) -> DiskUsage:
    """Return normalized capacity statistics for a mount point."""

    mount_point = Path(mount_point)

    if not mount_point.exists():
        raise FileNotFoundError(f"Filesystem path does not exist: {mount_point}")

    if not mount_point.is_dir():
        raise ValueError(f"Filesystem path is not a directory: {mount_point}")

    if not os.path.ismount(mount_point):
        raise ValueError(f"Path is not a mount point: {mount_point}")

    usage = shutil.disk_usage(mount_point)

    if usage.total <= 0:
        raise ValueError(f"Invalid filesystem capacity: {mount_point}")

    return DiskUsage(
        mount_point=str(mount_point.resolve()),
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        used_percent=round(usage.used / usage.total * 100, 1),
    )
