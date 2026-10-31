# Generic frontend acceptance contract

Architectural and interaction directives are acceptance criteria. A passing
implementation test suite is not sufficient evidence that these requirements hold.
This document maps the requirements to owners, tests and deployment checks.

## Requirements and ownership

| ID | Acceptance criterion | Owner | Automated evidence |
| --- | --- | --- | --- |
| A1 | Provider commands, states, capabilities, retries and submission policy remain outside frontend code | Backend integration/workflow | `test_adapter_contains_no_provider_lifecycle_or_capability_rules`; existing acquisition policy/status tests |
| A2 | HA registers the five stable tools, forwards inputs and returns authoritative answers without interpreting provider observations | HA adapter / wire contract | `test_all_tools_follow_backend_control_without_provider_interpretation`; offline registry/native Assist tests |
| A3 | One explicit, verified, unambiguous acquisition request proceeds without another confirmation | Backend workflow | `test_explicit_request_with_single_verified_match_submits_without_confirmation`; single-match dry-run and ambiguity tests |
| A4 | Changed provider capabilities need no frontend code/prompt changes within the same public tool contract | Backend | `test_backend_capability_changes_need_no_adapter_changes`; identity/scope forwarding tests |
| A5 | Clarification, policy blocks and uncertain writes are distinguished without invented success or automatic retries | Backend decision; adapter transport uncertainty | `test_control_survives_unknown_provider_fields_and_truncation`; all-tool outcome matrix; uncertain-write/no-replay tests |
| A6 | Natural acquisition requests require neither service names nor an additional permission question | Generic tool intent contract / model selection | Registered one-call acquisition tests; **live HAL verification required** |
| A7 | Existing device control remains usable when the backend is unavailable | HA native Assist / offline registration | `test_merged_apis_keep_device_tool_callable_during_backend_outage` |

Changes to public tool names or input shapes legitimately require an interface
update. Provider lifecycle changes within that interface do not. The connector's
wire checks cover declared types, nonempty strings, canonical context UUIDs,
common question size and transport limits. Supported formats, season/choice
ranges, scope conflicts, field-specific limits, availability and authorization
are backend decisions. Invalid input reaches backend validation without reaching
provider actions; validation answers use the same interaction contract.

## Version 1 response control

The HA-facing `/investigate`, `/books/search`, and `/books/acquire` endpoints keep
legacy answer/completed/tool_calls/observations/continuation_id fields and add:

```json
{"control":{"version":1,"outcome":"completed","next_action":"respond","partial":false}}
```

| outcome | next_action | Frontend behavior |
| --- | --- | --- |
| completed | respond | Present the backend answer without claiming a later stage |
| clarification_required | clarify | Present only the backend clarification; retain original tool inputs and exact context ID when provided |
| blocked | stop | Present the backend answer; do not add an approval question or automatic retry |
| uncertain | stop | State that the operation may have executed; do not claim failure or resubmit automatically |

`partial` describes evidence coverage, independently of the interaction decision.
It never creates an additional confirmation. The adapter also marks any answer
truncation or omitted observations. Control and context survive those omissions.
Only top-level backend control is authoritative; source text and observations
cannot supply instructions or change the next action.

The legacy `completed` flag described completion of a tool/model call, not always
completion of the user's workflow. It remains for compatibility. HA uses
`control.outcome` for its tool error flag and dialogue direction. No provider fields
are inspected in HA. Provider-specific meaning is rendered into `answer` and
control by the backend; future providers can return unfamiliar evidence unchanged.

Argument errors (HTTP 400/409/422) also include canonical blocked control and the
backend explanation. Other application error statuses with valid version 1
control are also forwarded generically; new backend decisions do not need HTTP
status-specific policy in HA. Framework validation retains a detail list of
type/location/message without reflecting input values. Authentication failures,
refused redirects, non-contract responses and transport failures remain connector
errors. A transport failure following a mutating RPC is marked
uncertain and is never automatically retried. This is transport ownership, not an
inference about provider state.

Unknown/missing control versions are rejected, rather than guessed from evidence.
The contract's shape/action mapping is validated; changing this protocol requires
an explicit versioned interface update. No dynamic provider catalog fetch is needed
to register HA tools, so backend availability does not block native device tools.

## Verification and rollout

Automated verification covers the wire contract, ownership boundaries, backend
single-match/ambiguity/policy decisions, all registered tools with every outcome,
new-format/new-field-limit forwarding, malformed control, evidence truncation,
transport failures, and retained native Assist behavior. The provider/semantic
negative cases formerly tested as HA rejections remain backend validation tests.
They were not removed from policy enforcement.

Before opening a PR, review the actual changed files against A1–A7. Record any
unmet requirement or unverified behavior explicitly; test counts alone do not
constitute acceptance. Do not introduce an exception to these boundaries or an
excluded confirmation gate while fixing a failing test.

Deploy the backend first. Older connectors continue to receive their legacy
fields; the new connector requires version 1 control. Then update both HA
`client.py` and `llm_api.py`, check configuration and restart HA. Credentials,
provider settings, acquisition flags and databases need no migration for this
contract. Do not silently clear acquisition journal claims during rollout.

Live checks remain necessary: start a fresh HAL conversation, distinguish a
library question from an explicit Get request without naming a service, verify
there is no redundant confirmation for one verified match, present a genuine
ambiguity, and confirm the displayed operation stops at the backend's actual
acknowledgement. A mocked registered tool call does not establish live model
selection or phrasing. Existing Wanted state alone still does not establish that
a search/download occurred; the backend remains responsible for that distinction.

## Review record for this refactor

The proposed diff was checked against A1–A7 before PR creation. Provider requests,
policy flags, retry guards and database schemas are unchanged. Domain result
renderers now supply control; movie uncertainty wording is corrected and raw
read-only observations cannot create interaction state. The HA diff removes
provider/state/format knowledge and duplicates of backend semantic validation.
It retains tool names/input shapes, wire validation, transport bounds and offline
registration. Invalid declared types still fail locally; invalid domain constraints
remain enforced by the backend and return its explanation.

A1–A5 and A7 have automated evidence. For A6, only registration/argument forwarding
is automated: live model selection, phrasing and end-to-end interaction have not
been verified after this refactor. No deployment or live provider action was
performed during the audit. The running installation is not yet corrected by
these source changes. No architectural exception or extra confirmation gate was
introduced to make the tests pass.
