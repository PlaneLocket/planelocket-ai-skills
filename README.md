# PlaneLocket AI

A self-hosted, Skill-aware Python agent for the PlaneLocket household.

PlaneLocket AI uses a local Ollama model to answer questions and investigate
household systems through explicitly authorized tools. Current capabilities
include Linux diagnostics, Emby media library searches, and read-only
InvenTree inventory queries.

The agent uses a centralized HTTP API, a bounded reasoning loop, and a
tool dispatcher that validates every requested operation. Skills provide
task-specific guidance without granting additional execution permissions.

## Design principles

- **Measurements are not conclusions.** Tools collect observations; the model interprets them and should distinguish evidence from inference.
- **Knowledge is available, not prescribed.** A Skill may include reference documents that the model can discover and request without hardcoding the diagnosis.
- **Capabilities are explicitly authorized.** Selecting a Skill does not grant arbitrary command execution. The dispatcher exposes only registered tools.
- **Models are replaceable.** Reasoning and tool execution are separated from the Ollama client, although Ollama is the currently implemented integration.
- **Failures should be visible.** Invalid tool arguments can be returned to the reasoning loop as observations, subject to a bounded tool-call budget.

## Current capabilities

- Discover Skills from the `skills/` directory and select one for a request.
- Generate a diagnostic **plan** without executing diagnostic tools.
- Run a bounded **investigation** using authorized read-only tools.
- Collect Linux memory and swap capacity, filesystem capacity, and CPU/memory/I/O Pressure Stall Information (PSI).
- Discover and securely read reference documents belonging to the selected Skill.
- Validate model-generated tool decisions and tool arguments.
- Return recoverable tool-argument errors to the model for possible correction.
- Search the household Emby library for movies, television series,
  episodes, artists, albums, and tracks.
- Find movies associated with actors using Emby person records.
- Search the household InvenTree parts catalog by name or model number.
- Retrieve InvenTree stock quantities, allocations, and storage locations.
- Expose investigations through a bearer-authenticated FastAPI endpoint.
- Record application events using centralized Python logging.

The available diagnostic tools are:

| Tool | Purpose |
| --- | --- |
| `get_memory_usage` | Memory and swap capacity |
| `get_disk_usage` | Filesystem storage capacity |
| `get_resource_pressure` | Linux CPU, memory, and I/O PSI |
| `list_references` | List reference filenames for the selected Skill |
| `read_reference` | Read a selected Skill reference; requires `filename` |

Knowledge tools are available during an investigation when the selected Skill is bound to the dispatcher.

## Requirements

- Linux for the current diagnostic backend and `/proc/pressure` PSI data.
- Python environment with the project's dependencies installed.
- A reachable Ollama service and a locally available model compatible with the project's Ollama client.

Development has been tested on Kvasir with Python 3.14 and Ollama `qwen3.5:9b`. This is a tested configuration, not a claim of exclusive compatibility.

## Run the tests

From the repository root, with the Python environment activated:

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
```

At commit `d985c7a`, the local test suite reported **95 passing tests**. This count is a historical checkpoint, not a guaranteed count for future commits.

## Run a local investigation

Start Ollama and ensure the configured model is available. From the repository root:

```bash
PYTHONPATH=src python - <<'PY'
from pathlib import Path

from planelocket_agent.agent import PlaneLocketAgent
from planelocket_agent.diagnostics.linux.backend import LinuxDiagnostics
from planelocket_agent.ollama import OllamaClient
from planelocket_agent.tools.dispatcher import ToolDispatcher

agent = PlaneLocketAgent(
    skills_directory=Path("skills"),
    client=OllamaClient(),
)

result = agent.investigate(
    user_request=(
        "Investigate current CPU contention, memory pressure, "
        "and storage I/O stalls. Distinguish resource capacity "
        "from resource contention and explain measurement limits."
    ),
    dispatcher=ToolDispatcher(LinuxDiagnostics()),
    max_tool_calls=8,
)

print("Completed:", result.completed)
print("Tool calls:", result.tool_calls)
print("Tools:", [item["tool"] for item in result.observations])
print(result.answer)
PY
```

The tool-call budget includes rejected tool requests. A completed investigation does **not** independently establish that the model's assessment is correct; examine its supporting observations.

## Skills and reference knowledge

Skills live under `skills/`. A Skill's `SKILL.md` provides task guidance. Optional documents under its `references/` directory supply factual background that can be retrieved during an investigation.

For example:

```text
skills/
  linux-health-check/
    SKILL.md
    references/
      pressure-stall-information.md
```

Reference access is scoped to the selected Skill. The loader validates reference paths and rejects attempts to escape the reference directory through symlinks.

**Important distinction:** PSI reports time spent waiting on constrained resources; it does **not** measure CPU utilization or directly measure device latency. Near-zero rolling PSI averages do not erase nonzero cumulative stall totals.

## Architecture

```text
User / HAL
    |
    v
FastAPI (/investigate)
    |
    v
PlaneLocketAgent
    |
    +--> SkillRegistry --> SkillSelector --> SkillLoader
    |                                           |
    |                                    Skill instructions
    |                                           |
    v                                           v
ReasoningAgent <-------------------------- OllamaClient
    |
    | Structured tool decision
    v
ToolDispatcher
    |
    +--> LinuxDiagnostics
    +--> Emby integration
    +--> InvenTree integration
    +--> KnowledgeProvider
    +--> MemoryRecorder (when configured)
    |
    v
Validated tool result
    |
    v
ReasoningAgent --> OllamaClient --> Final answer
```

Key implementation modules:

- `agent.py`: coordinates Skill selection, planning, and investigations.
- `registry.py`, `selector.py`, `loader.py`: Skill discovery, selection, instructions, and references.
- `reasoning.py`: bounded model/tool/observation loop.
- `tools/decisions.py`: validates structured model decisions.
- `tools/dispatcher.py`: authorized tool execution and argument checks.
- `tools/knowledge.py`: selected-Skill reference access.
- `diagnostics/linux/`: Linux diagnostic implementation.
- `ollama.py`: current model client.

## InvenTree integration verification

Verified on Kvasir, 2026-10-29.

### Implementation

- `skills/inventree-inventory/SKILL.md` provides inventory guidance.
- `integrations/inventree.py` implements authenticated, read-only API access.
- `ToolDispatcher` registers two inventory tools:
  - `search_inventory_parts(query: str)`
  - `get_inventory_stock(part_id: int)`
- Credentials are supplied through environment variables.
- Pagination and redirect handling include validation and loop protection.

### Live verification

An investigation for `SN74AHCT125N` returned:

- Two matching InvenTree parts.
- Available quantities of 5 and 10, totaling 15.
- Zero allocated units.
- Location: `Workshop/Electronics Bench/Component Bins`.

The agent completed the investigation using three tool calls:

1. `search_inventory_parts`
2. `get_inventory_stock`
3. `get_inventory_stock`

The existing FastAPI `/investigate` endpoint was also tested
successfully with bearer authentication.

### Automated tests

The complete test suite passed:

- 156 tests passed.
- 8 subtests passed.

These results describe the verified state on 2026-10-29,
not a guarantee about future inventory quantities or deployments.

## Known limitations and next steps

- **Reference use is not yet reliable.** In live tests, Qwen discovered references but did not consistently call `read_reference`; successful retrieval and improved interpretation still need verification.
- **PSI interpretation needs scrutiny.** Live model assessments have sometimes confused pressure with utilization or overlooked historical cumulative stalls.
- **Regression coverage requires continued maintenance.** The test suite
  passed 156 tests and 8 subtests on 2026-10-29. Future integrations
  should include focused tests for new behavior and failure conditions.
- **Knowledge binding currently rebuilds a dispatcher using its private backend attribute.** This is a temporary integration that should be replaced with clean provider composition.
- **Persistent memory is not implemented.** A future phase will explore controlled storage and retrieval of facts and investigation history.
- **The current tool set is read-only and Linux-focused.** It does not provide arbitrary shell execution or remote host management.

## Development workflow

### Development environment

- Primary development host: Kvasir.
- IDE: VS Code using Remote SSH.
- Repository: `/home/looper/projects/planelocket-ai-skills`.
- Python virtual environment: `.venv`.
- Local inference: Ollama using the attached NVIDIA RTX 3060.
- Source control: GitHub feature branches and pull requests.

### Working practices

This project is developed collaboratively, with the operator learning
Python while implementing the system.

- Explain Python concepts, architectural decisions, and tradeoffs.
- The operator writes and edits code in VS Code.
- Use the VS Code integrated terminal when commands are necessary.
- Give one meaningful implementation step at a time.
- Inspect existing code before recommending changes.
- Reuse existing architecture rather than introducing duplicate services.
- Prefer focused changes that deliver working functionality.
- Write tests for meaningful behavior and regression protection.
- Avoid redundant tests and repeated verification of established behavior.
- Validate integrations against live services when appropriate.
- Review changes before committing.
- Submit changes through pull requests rather than directly to main.

### Session continuity

Before proposing architectural changes, review this README and the
relevant existing implementation.

Do not assume previously discussed infrastructure details are current.
Consult repository documentation and configuration.

At the end of a development session, record:

1. Completed functionality and verification results.
2. Important architectural decisions.
3. Outstanding problems and limitations.
4. The next implementation milestone.

Do not repeat completed discovery or verification work without a
specific technical reason.


## HAL household knowledge integration

The [Home Assistant connector](homeassistant/README.md) adds one read-only household
question tool to the existing native Ollama conversation agent through HA's LLM API
extension mechanism. Source, tests and HA-only dependencies are isolated under
`homeassistant/`; the backend and Emby implementation remain independent of HA.
Production installation and voice/end-to-end acceptance on Frigg are separate
operator tasks and have not been performed by this change.
