# TV acquisition through HAL

TV acquisition uses the explicit write-capable `acquire_tv` tool. Movie acquisition
continues through `acquire_movie`, and `ask_household` remains read-only. Both media
types use the existing Seerr resolver, complete paginated search, and
`SEERR_AUTO_REQUEST` authorization switch. Keep that switch false during rollout.

## Conversation and scope

Examples:

- `Get Example Series season 2` selects season 2, not every season.
- `Get Example Series seasons 1 and 3` selects those seasons.
- `Get all seasons of Example Series` selects the regular seasons currently
  listed with episodes; it excludes specials and unannounced future seasons.
- `Get Example Series` asks which seasons to acquire after resolving the show.
- Ambiguous series names ask for the premiere year before continuing. The
  original season selection survives show disambiguation.
- Specials require explicit season 0. Seerr must also allow specials in its own
  configuration. Individual episode acquisition and 4K requests are not supported.

HAL supplies `title` separately from `question`. `year` is the series premiere
year, never the season number. `seasons` is a nonempty list of distinct integers
0–999, with at most 100 selections. `all_seasons=true` is an alternative to that
list; sending both is rejected. If neither is provided, the backend asks rather
than inferring all seasons. A literal trailing title year is split before search.

## HTTP contract

The existing authenticated `POST /investigate` accepts:

```json
{"question":"Get Example Series season 2","intent":"acquire","media_type":"tv","title":"Example Series","year":2020,"seasons":[2]}
```

A season clarification follows the same endpoint and includes its server-issued ID:

```json
{"question":"season 2","intent":"acquire","media_type":"tv","title":"Example Series","continuation_id":"<returned UUID>","seasons":[2]}
```

Simple season-number replies, `season 2`, `seasons 1 and 3`, `1-3`, and `all seasons`
are also recognized when structured scope is absent on a season continuation.
Year/newest replies work during show clarification. The stored title and TMDB ID
remain authoritative, regardless of a caller's replacement title. Movie and TV
continuations cannot be interchanged. Invalid conversational replies retain their
ID; invalid catalog choices receive a fresh season clarification. Expired,
consumed and unknown IDs are rejected. Each valid transition consumes its old ID
atomically before evaluation or submission; subsequent clarification creates a
new 15-minute ID. Clarifications have `completed=true` and a continuation ID, not a
transport failure.

The existing continuation table gains an additive JSON `context` column for type,
stage, show identity and season scope. Old movie records default to `{}` and keep
working; existing movie candidates and request records are retained.

## Season status and submission

The backend checks `mediaInfo.seasons` and season lists in existing standard
requests. Whole-series partial availability does not prevent getting other missing
seasons. Available, pending, processing and partially available seasons are not
requested again. Active/failed request records holding a season also block a
second request, matching Seerr's request logic. Declined/completed request records
and 4K requests do not hold standard seasons. Blocklisted or unverifiable selected
season state blocks submission. Missing season rows under a fully available series
are treated as unverifiable, rather than assuming they are absent.

A mixed selection reports selected, available, requested, in-progress and eligible
missing seasons. Only eligible missing seasons can reach submission. The backend
fetches fresh details and checks identity, selected-season status and policy again
immediately before one POST. That POST contains a numeric season list, never the
expanding string `all`. Catalog changes cannot add a new season during the recheck.
Seasons without listed episodes cannot be submitted explicitly.

With automatic acquisition disabled, the result contains
`submission={"submitted":false,"reason":"dry_run"}` and explicitly says no request
was submitted. Existing availability/request outcomes likewise submit nothing.
Successful acknowledgements report the season list Seerr actually accepted.
A POST exception or malformed acknowledgement produces `submitted=null` and an
uncertain outcome, not a success or a false claim that nothing happened. No POST
is retried automatically; inspect Seerr before an explicit retry.

## Validation and deployment

Run the commands in [the acquisition guide](SEERR_ACQUISITION.md#validation).
Regression tests cover real HTTP routing, TV show/year/season transitions,
per-season mixed availability and request state, specials, catalog/identity
changes, strict argument validation, expiry/replay, typed continuation isolation,
pre-POST policy/status checks, and uncertain outcomes. All external services are
mocked. HA tests use the real API registry, native Ollama formatter and loopback
transport. These establish contracts, not live model compliance.

Deploy backend first on Kvasir, preserving `.env` and `SEERR_AUTO_REQUEST=false`.
Record the prior commit and back up the configured Seerr SQLite database using a
consistent SQLite backup before restarting; the configured path may differ from
the source default. Run backend tests and restart `planelocket-ai.service`, then
verify health through the existing HTTPS ingress.

On Frigg, back up the installed integration, then replace **client.py** and
**llm_api.py** from `homeassistant/custom_components/planelocket_ai`. Validate
configuration and restart HA. No new dependencies are required. Use fresh HAL
conversations to verify a specific season, an omitted-scope clarification, and an
already available/requested season. Inspect tool arguments and actual returned
season lists; do not perform a live acquisition POST during rollout.

Rollback both backend source and the two HA files to the recorded versions,
keeping auto acquisition false, then restart both services. Close TV conversations
and do not reuse their continuation IDs after rollback. The additive context
column can remain in the database; restoring the prior schema is unnecessary.

API field/status references were checked against Seerr source:
[TV details](https://github.com/seerr-team/seerr/blob/develop/server/models/Tv.ts),
[request creation](https://github.com/seerr-team/seerr/blob/develop/server/entity/MediaRequest.ts),
and [status constants](https://github.com/seerr-team/seerr/blob/develop/server/constants/media.ts).
Live deployment/version compatibility remains to be verified on the household host.
