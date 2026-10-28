"""Linux Pressure Stall Information (PSI) diagnostics."""

from pathlib import Path

from planelocket_agent.diagnostics.models import (
    PressureSample,
    ResourcePressure,
)


def _parse_pressure_file(path: Path) -> dict[str, PressureSample]:
    """Parse one Linux /proc/pressure resource file."""

    samples = {}

    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()

        if not parts:
            continue

        kind = parts[0]

        if kind not in ("some", "full"):
            raise ValueError(f"Unknown pressure type: {kind}")

        if kind in samples:
            raise ValueError(f"Duplicate pressure type: {kind}")

        fields = {}

        for item in parts[1:]:
            key, separator, value = item.partition("=")

            if not separator or key in fields:
                raise ValueError(f"Invalid pressure field: {item}")

            fields[key] = value

        required = {"avg10", "avg60", "avg300", "total"}

        if fields.keys() != required:
            raise ValueError(f"Invalid pressure fields in {path}")

        try:
            sample = PressureSample(
                avg10=float(fields["avg10"]),
                avg60=float(fields["avg60"]),
                avg300=float(fields["avg300"]),
                total_microseconds=int(fields["total"]),
            )
        except ValueError as exc:
            raise ValueError(f"Invalid pressure values in {path}") from exc

        if (
            not 0 <= sample.avg10 <= 100
            or not 0 <= sample.avg60 <= 100
            or not 0 <= sample.avg300 <= 100
            or sample.total_microseconds < 0
        ):
            raise ValueError(f"Pressure values out of range in {path}")

        samples[kind] = sample

    if "some" not in samples:
        raise ValueError(f"Missing 'some' pressure measurement in {path}")

    return samples


def get_resource_pressure(
    pressure_directory: Path = Path("/proc/pressure"),
) -> ResourcePressure:
    """Read CPU, memory, and I/O pressure from Linux procfs."""

    cpu = _parse_pressure_file(pressure_directory / "cpu")
    memory = _parse_pressure_file(pressure_directory / "memory")
    io = _parse_pressure_file(pressure_directory / "io")

    if "full" not in memory or "full" not in io:
        raise ValueError("Missing required full pressure measurement")

    return ResourcePressure(
        cpu_some=cpu["some"],
        cpu_full=cpu.get("full"),
        memory_some=memory["some"],
        memory_full=memory["full"],
        io_some=io["some"],
        io_full=io["full"],
    )
