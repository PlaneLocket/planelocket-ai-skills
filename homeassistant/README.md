# HAL household knowledge connector

**Status:** Development implementation. Not installed or end-to-end validated on Frigg.

This custom Home Assistant integration exposes the existing PlaneLocket AI API to
HAL, the native Ollama conversation agent. It registers a separate **PlaneLocket AI**
LLM API with one read-only tool, `ask_household(question)`. Select it
**alongside Assist**, not instead of Assist. No Home Assistant core, Ollama agent,
Emby implementation, speech recognition, or device-control changes are required.

## Compatibility and architecture

Development targets **Home Assistant Core 2026.10.1**, Python 3.14, and its supported
`homeassistant.helpers.llm` extension API. The automated suite uses that actual HA
release, including its registry, API merger, config-flow manager and tool dispatch.
Other releases require validation before production use. This is custom code using
a supported extension interface, not an official Home Assistant integration.

1. Home Assistant retains its existing local device-command handling.
2. Native Ollama/HAL receives both Assist and PlaneLocket AI tools.
3. For household facts, HAL calls the connector's question tool.
4. The async connector posts `{"question": "..."}` to the existing bearer-protected
   `POST /investigate` endpoint through the configured HTTPS origin.
5. The independent backend selects its Skill and uses its existing tools.
6. HAL receives a bounded answer plus observations, completion status and explicit
   truncation markers. It is instructed to use the evidence and disclose failures.

Home Assistant namespaces tool names when APIs are merged. The model may therefore
see a name such as `planelocket-ai__ask_household`; use the registered
schema rather than hardcoding a merged name. The connector does no network I/O
while registering the API or assembling a request's tool list. Backend downtime
therefore does not prevent API merging or remove Assist's tools.

**No backend HA dependency is added.** Source and tests are isolated under this
folder. The connector describes a stable read-only household lookup role, not a
catalog of backend skills or providers. The backend owns skill selection and
source support. Adding a read-only backend skill that uses the existing HTTP
contract does not require changing the connector prompt, tool description or
HAL's custom instructions. This does not imply that every source is supported:
HAL must use the returned evidence and disclose unsupported or failed lookups.

Keep provider-specific query guidance in backend skills. Connector instructions
retain only the shared evidence, partial-result and read-only boundaries; native
Assist continues to own device states and commands.

## Installation and configuration

Perform production installation separately with the operator. The detailed
[Frigg deployment checklist](https://github.com/PlaneLocket/planelocket-infrastructure/blob/main/frigg/docs/HAL_HOUSEHOLD_KNOWLEDGE.md)
covers backup, staged deployment, acceptance tests and rollback; that link becomes
available when the accompanying infrastructure PR is merged.

1. Record Frigg's actual Core version, current HAL/Ollama configuration, selected
   LLM APIs, existing local-command preference and baseline device-command results.
   Make a native HA backup and preserve its recovery material privately.
2. From an explicitly reviewed Git commit in this repository, copy only
   `homeassistant/custom_components/planelocket_ai/` to
   `/config/custom_components/planelocket_ai/`. Do not copy tests, Python environments
   or the backend into HA. There is no HACS repository/release packaging in Phase I.
3. Run `ha core check`, then restart Home Assistant during the agreed maintenance
   window. A YAML check alone does not establish that the custom integration works.
4. Go to **Settings → Devices & services → Add integration → PlaneLocket AI**.
   Enter `https://ai.planelocket.com` and the existing bearer token from private
   secret storage. No YAML or source-code token is needed.
5. Setup checks `GET /health` (without authorization). This verifies reachability,
   **not token validity**: the API has no documented authenticated validation route
   that avoids running an investigation. Authentication is checked on the first
   household question. Do not invent an authenticated health endpoint.
6. Open the existing Ollama integration's HAL conversation configuration and retain
   **Assist** in its LLM API selection while adding **PlaneLocket AI**. Labels vary
   by HA version. Do not select any administrative Home Assistant API. Preserve the
   existing model, local-command preference, pipeline, Whisper and device exposure.
7. Begin a fresh text conversation and perform the acceptance and regression checks
   below before using voice. No HAL prompt replacement is needed; the connector's
   API contributes its own household-lookup instructions.

Exactly one connector instance is supported. Use the entry menu's **Reconfigure**
to change the endpoint or token. A rejected lookup starts HA's reauthentication
flow. Both replacement flows retain the entry/API ID, avoiding stale HAL selections.
They verify reachability only and check the replacement token on the next lookup.

## Credential and data handling

- Store the token only in the connector's private config entry. The password UI is
  masked; this does **not** encrypt HA config-entry storage. Protect `.storage` and
  native backups. Never add the token, `.storage`, `.env` or HTTP header dumps to Git.
- The connector never logs questions, credentials, response bodies or raw exceptions.
  Remote error bodies are not returned to HAL. An echoed configured token is redacted
  from successful response strings and keys before they reach conversation history.
- The backend retains its own private Emby credentials. Frigg receives only the API
  bearer token. Headers are sent only to `/investigate` on the configured HTTPS origin;
  redirects are rejected and certificate verification remains enabled.
- Household questions and returned evidence enter the existing HAL conversation
  context. Home Assistant traces/history and operator-enabled debug logs can retain
  household data. Avoid enabling verbose HTTP/Ollama logging during credential entry.
- Phase I exposes a read-only question capability backed by the current read-only
  dispatcher. **Tool annotations and prompts are not backend authorization.** Before
  adding write tools to the shared endpoint, enforce backend permissions/scopes.
  Shared voice access likewise does not confer per-person authorization to future
  sensitive Paperless/health data. Design that authorization before enabling it.

## Limits and failures

| Boundary | Policy |
| --- | --- |
| Input | Nonempty question, maximum 2,000 characters after trimming |
| Health | 10-second total deadline |
| Investigation | 120-second total deadline, including response-body reads; connection timeout up to 10 seconds |
| HTTP body | 256 KiB maximum, enforced on advertised length and decoded streamed bytes |
| Tool result | At most 16 KiB of UTF-8 JSON data; answer at most 6,000 characters |
| Overflow | Reject oversized HTTP responses; mark shortened answers and omitted observations explicitly |
| Retries | None automatically for model-backed POST requests |
| Failure | Sanitized error code/message for auth, timeout, connection, service, schema or size failures |
| Incomplete | `completed: false` is an error tool result, even if an answer string exists |

A shortened answer or omitted observation is **partial**, not proof of a complete
library list. Existing API `completed: true` means the reasoning loop finished;
it does not independently establish evidence quality or correctness. The model
must still use observations. Remote data is evidence, not permission or instructions
for additional device actions.

A client timeout/cancellation does not guarantee that the synchronous backend stops
its investigation. Do not repeatedly retry a slow request. Check backend load with
the operator; proxy timeouts may also end a request before the connector's deadline.
HAL plus the backend may run several sequential inference calls on the same Kvasir
GPU, so latency must be measured separately from deterministic transport tests.

## Acceptance and regression checks (operator, not yet performed)

1. Ask HAL: **“What movies starring Harrison Ford do we have?”** Confirm a household
   tool call and backend `search_people` followed by `get_person_movies`, using the
   returned person ID. Verify HAL's titles against the actual observations/library.
   Emby associations do not independently verify a specific starring credit.
2. Test an absent title, an ambiguous person, and a narrow follow-up question.
   HAL must not answer library availability from general film knowledge.
3. Repeat previously working native device commands and confirm the same intended
   entities. Include one command handled locally and a native Assist tool command.
4. Use an isolated test environment or mock endpoint for timeout, malformed response
   and invalid-auth cases. Do not break production DNS, stop shared services, or
   change the production token merely to test failure handling.
5. Confirm a backend lookup failure does not remove native Assist tools or change
   local command handling. Test this on an isolated HA instance/mock backend first.
6. Repeat the successful lookup through existing voice → faster-whisper → HAL → TTS.
   Record version/model, elapsed time, actual tools, evidence and outcome without tokens.

The fixture under `tests/fixtures/` is deliberately synthetic. It establishes connector
transport and evidence preservation; it is not an inventory export or proof that
HAL/Qwen chooses tools reliably. Production end-to-end acceptance remains outstanding.

## Development validation

Use a separate Python 3.14 environment; do not install these dependencies into the
production backend's venv or Frigg's managed HA environment.

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -e . -r homeassistant/requirements-test.txt
PYTHONPATH=src python -m unittest discover -s tests -q
python -m pytest -c homeassistant/pytest.ini homeassistant/tests -q
ruff check --config homeassistant/ruff.toml homeassistant
ruff format --check --config homeassistant/ruff.toml homeassistant
```

The tests exercise real HA config flows/registration/merging and a synthetic native
device tool, never actual devices or household endpoints. Loopback HTTP tests cover
streaming and timeout behavior. CI also stages the custom integration at repository
root for the standard Home Assistant hassfest action. The existing backend tests
had four stale expectations for its already-added media tools/`arguments` envelope;
only those expectations were updated, without changing backend or Emby behavior.

## Troubleshooting and rollback

- Integration missing: verify the exact directory nesting, restart HA, refresh the
  browser, and inspect sanitized startup errors. Preserve the existing custom components.
- Cannot connect: verify Frigg resolves the internal hostname to Heimdall and can
  validate its certificate. Check the AI-specific SNI/source ACL and narrow upstream
  firewall path with the operator. Do not disable TLS validation or bypass ingress.
- Auth rejected: use Reconfigure/reauthentication with the private existing token.
  A 403 can also reflect gateway policy; it is not proof of an incorrect token.
- Tool absent: confirm the entry loaded, and **both Assist and PlaneLocket AI** are
  selected for the existing HAL conversation agent. Start a new conversation.
- Slow/no answer: record elapsed time and sanitized error code; investigate proxy
  timeout and shared-model contention before changing limits.

Before removing or disabling the connector, edit HAL's API selection to remove only
PlaneLocket AI and retain Assist. Otherwise HAL may reference an API that is no longer
registered. Start a fresh conversation and verify device control. Then remove the
connector entry; remove its directory and restart only if desired. For an upgrade,
back up its previous directory privately, replace from a reviewed commit, restart,
verify selection, and rerun acceptance checks. Restore the previous directory or use
the removal sequence if needed. No backend, proxy or Emby changes are part of rollback.

## Reference implementation contracts

- [Home Assistant LLM API extension documentation](https://contributors.home-assistant.io/core/internals/llm-api/)
- [Ollama multi-API configuration at 2026.10.1](https://github.com/home-assistant/core/blob/2026.10.1/homeassistant/components/ollama/config_flow.py)
- [Home Assistant API registration, merger and tool contracts at 2026.10.1](https://github.com/home-assistant/core/blob/2026.10.1/homeassistant/helpers/llm.py)
- [Existing backend HTTPS deployment](../docs/PRODUCTION_DEPLOYMENT.md)


## Movie acquisition

The separate `acquire_movie` tool supports structured title/year and server-issued
continuations. `ask_household` stays read-only. See
[the acquisition contract and rollout guide](../docs/SEERR_ACQUISITION.md).
Keep `SEERR_AUTO_REQUEST=false` throughout dry-run validation.


## TV acquisition

`acquire_tv` is a separate write-capable tool. It requires `question` and a
canonical series `title`, with optional premiere `year`, explicit `seasons`,
`all_seasons`, and `continuation_id`. If season scope is omitted, the backend asks
which seasons; it never assumes the whole series. Specials require explicit
season 0. Keep automatic acquisition disabled during rollout.

See [TV scope, API contract, deployment and rollback](../docs/TV_ACQUISITION.md).
The update requires both `client.py` and `llm_api.py` on Frigg, plus the backend
update on Kvasir; no dependency changes are needed.

## Book library and acquisition

`search_books` reads books visible to the dedicated Calibre-Web NextGen account.
`acquire_book` requires an explicit acquisition request and a numbered offer
selection; library lookup never creates a book job. Book policy is controlled by
`CWNG_AUTO_REQUEST`, separately from movie/TV policy. It defaults to false.
NextGen Book Sources and account access must be configured separately for jobs.

See [book API, configuration, selection and rollout](../docs/BOOK_ACQUISITION.md).
Update the backend on Kvasir and both `client.py` and `llm_api.py` on Frigg.
