---
name: linux-health-check
description: >
  Inspect Linux servers for system health problems.
  Use when asked about CPU, memory, disk utilization,
  failed services, or general Linux server health.
---

# Linux Health Check

## Objective

Evaluate the health of a Linux server.

## Procedure

1. Identify the target server.
2. Confirm that the target is authorized.
3. Collect system health information using approved tools.
4. Analyze the collected information.
5. Identify warnings and critical conditions.
6. Recommend corrective actions.

## Safety Rules

- Do not modify system configuration.
- Do not restart services without authorization.
- Do not execute destructive commands.
- Report failed checks rather than assuming success.
- Distinguish confirmed findings from possible causes.

## Output Format

Provide:

- Overall health status
- CPU and memory utilization
- Disk utilization
- Failed systemd services
- Docker container status, if applicable
- Warnings
- Recommended actions
