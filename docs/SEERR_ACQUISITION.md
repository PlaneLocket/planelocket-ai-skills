# Movie acquisition through HAL

HAL exposes two distinct tools: `ask_household` explicitly sends
`intent=investigate` and remains read-only; `acquire_movie` is write-capable and
requires an explicit user acquisition request. Device control still uses Assist.
TV season acquisition is available through the separate `acquire_tv` tool; see
[TV acquisition](TV_ACQUISITION.md) for explicit season scope and rollout details.

## Contract

Initial `POST /investigate` (normal bearer authentication required):

```json
{"question":"Get Example Film","intent":"acquire","title":"Example Film"}
```

The backend routes acquisition directly to the Seerr preparation workflow rather
than asking the reasoning agent to choose a tool. Ambiguous exact movie matches
return candidate titles, years, media IDs, and a top-level `continuation_id`.
The HA client preserves that ID even when large observations are omitted.

Follow-up:

```json
{"question":"2026","intent":"acquire","continuation_id":"<returned UUID>","year":2026}
```

HAL must carry the returned ID in the same conversation. `the new one`, `newest`,
and `latest` also work without a year. Only a unique candidate from the stored
snapshot may be selected. Invalid selections retain the ID for clarification.
Expired, unknown, and already-consumed IDs are rejected. IDs expire after 15
minutes and are consumed atomically. A selected release is resolved again against
Seerr, including a check against the stored media ID, before policy evaluation.
Do not share IDs between conversations. The connector relies on the conversation
agent to return the ID; it does not infer or globally cache pending selections.

Canonical title and year are separate. A trailing `(2026)` in a title is split
before search; conflicting structured and parenthesized years cannot submit.
Older question-only clients still support imperative acquisition requests such as
`Go get Example Film`. Complex legacy reformulations ask for a title instead of
silently claiming availability. Explicit `intent=investigate` always suppresses
acquisition routing.

## Policy and results

Keep `SEERR_AUTO_REQUEST=false` during rollout. This setting is enforced by the
existing authorization policy and confirmation endpoint. With it disabled, a
resolved requestable movie returns `submission.submitted=false`, reason `dry_run`,
and an answer explicitly saying no request was submitted. Available, requested,
in-progress, ambiguous, and unmatched movies cannot submit. Model parse/context
errors on ordinary investigation return an incomplete response rather than an
unhandled value/JSON exception. No automatic HTTP POST retries are performed.

## Validation

All external Seerr and model services are mocked in regression tests:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SEERR_AUTO_REQUEST=false .venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest -c homeassistant/pytest.ini homeassistant/tests -q
.venv/bin/ruff check --config homeassistant/ruff.toml homeassistant
.venv/bin/ruff format --check --config homeassistant/ruff.toml homeassistant
```

Backend tests include the real FastAPI request path, candidate snapshot migration,
concurrent single-use consumption, numeric/newest selection, ID replay/expiry,
identity changes, dry-run and existing availability/request statuses. HA tests use
the real API registry and Ollama schema formatter plus loopback HTTP transport.
These tests do not establish live HAL model compliance or deployed configuration.

## Deployment and rollback

On Kvasir, repository `/home/looper/projects/planelocket-ai-skills`, record the
current commit before updating. Preserve the private `.env` and ensure
`SEERR_AUTO_REQUEST=false`. Run the backend tests using `.venv`, then restart
`planelocket-ai.service` and check `/health` through the existing HTTPS ingress.
Follow `PRODUCTION_DEPLOYMENT.md` for the verified service topology.

Deploy `homeassistant/custom_components/planelocket_ai` to Frigg using the existing
integration installation procedure in `homeassistant/README.md`; restart Home
Assistant. Confirm the selected PlaneLocket LLM API exposes both tools. In a fresh
HAL conversation request an ambiguous movie, choose a year, and verify the tool
trace reuses the exact continuation ID and reports no submission. Repeat with a
different title. Do not enable automatic acquisition as part of this validation.

Rollback both backend and HA component to their recorded prior versions and
restart both services. The SQLite migration only adds a `candidates` column with
an empty-list default; old code can still read the original columns. No existing
request records are removed. Outstanding new continuations may require a fresh
search after rollback. No deployed validation was performed from the cloud test
workspace.

## Broad title searches

Ordinary Seerr searches can include many unrelated substring matches. The search
collector supports up to 2,000 results / 100 pages, using batches of at most six
parallel read-only GETs. It checks a 40-second collection budget before scheduling
another batch and after collection; each GET has a socket timeout of at most ten
seconds, reduced to the remaining budget. Already-running requests are drained
before returning. This is a bounded collection budget, not a hard wall-clock
transport deadline.

All pages must agree on counts and page numbers; the collected count must match,
and media identities are deduplicated by `(mediaType, id)`. Raw entry count is
checked against the reported count before deduplication. Consistent repeated
identities are collapsed in first-seen order; conflicting title, original title,
or release-date data for one identity keeps the search incomplete. Different
identities that match the same title/year remain ambiguous. Search responses
include `unique_results` and `duplicates_omitted` alongside the reported raw count.
Incomplete resolution evidence retains the collector's reason and page/count
metadata for diagnosis. A failed, changing, over-limit, or
expired search returns no usable results with `complete=false`. The resolver
therefore cannot authorize from an incomplete set, even if page one contains an
exact title/year match. This preserves late-page ambiguity checks.

Seerr's `year:` provider is deliberately not used as proof of a complete search:
its implementation combines only the first movie and TV result pages and reports
a single page. A returned set of 20 movies can hide additional movie matches.
See [Seerr search provider implementation](https://github.com/seerr-team/seerr/blob/develop/server/lib/search.ts).
The title and year are still matched separately by the local resolver after full
ordinary-search collection. No cap or submission-policy setting is changed on the
running host until deployment; `SEERR_AUTO_REQUEST=false` remains required for
live rollout checks.
