# Linux Pressure Stall Information (PSI)

## Purpose

Linux Pressure Stall Information (PSI) measures time during which
tasks experience resource-related stalls.

PSI measures resource contention, not resource utilization.

System-wide PSI measurements are exposed through:

- `/proc/pressure/cpu`
- `/proc/pressure/memory`
- `/proc/pressure/io`

## Resources

### CPU

CPU PSI measures time during which runnable tasks cannot execute
because CPU execution capacity is unavailable.

CPU utilization and CPU pressure are different measurements.

A CPU can be fully utilized without significant scheduling
contention, such as when one CPU-bound task occupies each CPU
and no additional runnable tasks are waiting.

### Memory

Memory PSI measures stalls associated with memory pressure,
including memory reclaim activity.

Memory utilization alone does not establish whether tasks
are experiencing memory-related stalls.

### I/O

I/O PSI measures time during which tasks experience I/O-related
stalls.

I/O PSI does not directly measure storage-device latency,
throughput, or utilization.

## Pressure categories

`some` measures time during which at least one task experiences
a resource-related stall.

`full` measures time during which all non-idle tasks in the
measured group are stalled on that resource.

System-wide CPU `full` has special kernel-dependent semantics
and should not be interpreted as an ordinary CPU saturation
measurement.

## Measurement fields

- `avg10`: Recent pressure average over approximately 10 seconds.
- `avg60`: Recent pressure average over approximately 60 seconds.
- `avg300`: Recent pressure average over approximately 300 seconds.
- `total`: Cumulative stall time in microseconds.

The averages are percentages of elapsed time.

Cumulative totals are not instantaneous measurements. Comparing
totals from two observations can reveal accumulated stall time
between those observations.

A displayed average of `0.00` does not necessarily mean that
no stalls occurred. Small or transient stalls may not be
visible at the reported precision.

## Related measurements

Memory capacity, CPU utilization, disk capacity, storage latency,
and swap activity are distinct measurements.

Current swap occupancy does not establish whether swapping
occurred previously.

Current filesystem free space does not establish storage
performance.

## Scope and limitations

System-wide PSI measurements describe aggregate resource
pressure rather than individual application performance.

PSI measurements do not independently establish the cause
of a performance problem.

A lack of measurable PSI pressure does not rule out application
errors, hardware faults, configuration problems, or intermittent
performance issues.

## Primary references

Linux kernel documentation:

- https://docs.kernel.org/accounting/psi.html
- https://www.kernel.org/doc/html/latest/accounting/psi.html