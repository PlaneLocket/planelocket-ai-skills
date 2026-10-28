"""Linux-specific memory diagnostics."""

from pathlib import Path

from planelocket_agent.diagnostics.models import MemoryUsage


def get_memory_usage(
    meminfo_path: Path = Path("/proc/meminfo"),
) -> MemoryUsage:
    """Read Linux memory information and return normalized measurements."""

    values = {}

    for line in meminfo_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")

        if not separator:
            continue

        parts = value.strip().split()

        if len(parts) != 2 or parts[1] != "kB":
            continue

        try:
            values[key] = int(parts[0])
        except ValueError as exc:
            raise ValueError(f"Invalid memory value for {key}") from exc

    required = (
        "MemTotal",
        "MemAvailable",
        "SwapTotal",
        "SwapFree",
    )

    for key in required:
        if key not in values:
            raise ValueError(f"Missing required memory field: {key}")

    total = values["MemTotal"]
    available = values["MemAvailable"]
    swap_total = values["SwapTotal"]
    swap_free = values["SwapFree"]

    if total <= 0:
        raise ValueError("Invalid total memory")

    if not 0 <= available <= total:
        raise ValueError("Invalid available memory")

    if not 0 <= swap_free <= swap_total:
        raise ValueError("Invalid swap memory values")

    kib = 1024

    return MemoryUsage(
        total_bytes=total * kib,
        available_bytes=available * kib,
        used_bytes=(total - available) * kib,
        used_percent=round((total - available) / total * 100, 1),
        swap_total_bytes=swap_total * kib,
        swap_used_bytes=(swap_total - swap_free) * kib,
    )
