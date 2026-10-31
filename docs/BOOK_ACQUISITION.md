# Books through Calibre-Web NextGen

HAL exposes `search_books` for read-only library lookup and `acquire_book` for
explicit acquisition. These tools use the existing PlaneLocket bearer-protected
backend. Device control, movie/TV tools, and the Seerr switch retain their existing
paths. The implementation targets the installed NextGen **v4.1.52** API.

## Configuration

Store these privately in Kvasir's project `.env`:

```dotenv
CWNG_URL=http://10.10.1.20:8083
CWNG_USERNAME=planelocket-ai
CWNG_PASSWORD='private-account-password'
CWNG_AUTO_REQUEST=false
```

`CWNG_URL` is an origin, without a path, query, or embedded credentials. HTTPS is
supported; the configured household address uses internal HTTP. Credentials and
session cookies stay on Kvasir. Frigg continues using its existing PlaneLocket
backend token. Do not paste credentials into chat or commit `.env`.

Use a dedicated NextGen account with the intended library visibility. Library
lookup does not require administrator, edit, delete, upload or acquisition rights.
Search describes only books visible to that account, not a household-wide proof
of absence. Acquisition requires NextGen's `monolibrary` view; personal-library
mode remains usable for lookup.

Book acquisition also requires the administrator to enable **Book Sources**,
configure appropriate OPDS/Newznab connections and runtime, and grant the account
acquisition access. These are NextGen settings, not changes this integration makes.
Without them, lookup still works and acquisition reports unavailable access.
NextGen's acquisition auto-approval permission is separate: an accepted job can be
`awaiting_approval`. The adapter does not grant permissions, configure sources,
relax source network policy, or approve jobs.

`CWNG_AUTO_REQUEST` defaults to false and is independent of `SEERR_AUTO_REQUEST`.
Keep the book flag false during initial validation. Existing movie/TV acquisition
may remain enabled. The book flag allows or blocks creation of acquisition jobs;
it does not prevent session login, library reads, or source searches. NextGen may
persist expiring offer/search tokens while serving catalog GET requests.

## API and conversation

Both endpoints require the existing `Authorization: Bearer ...` backend token.

```http
POST /books/search
{"query":"Example Author"}

POST /books/acquire
{"question":"Get Example Book by Example Author","title":"Example Book","author":"Example Author","format":"EPUB"}
```

Library search accepts up to 500 characters and returns selected metadata, visible
record count and a completeness flag. Up to 25 records are shown to HAL. This is
library search, not external bibliography research. It never creates acquisition
jobs. Library pagination is capped at 500 records; changing counts, duplicate IDs,
missing pages and the cap prevent a complete/absent claim. Acquisition refuses to
submit when its library check is incomplete.

Acquisition requires separate `question` (up to 2000 characters) and `title` (up
to 500). Optional `author` is up to 300 characters; optional `format` is EPUB, PDF,
or MOBI. Supply author/format only when requested by the user. Unknown fields,
source URLs and caller-supplied offer IDs are rejected.

The backend first checks matching library files. It searches only administrator
configured sources using server-issued navigation/search selections. It presents
numbered offers with source, title, authors, language and format. Even one result
requires the user to choose it. A follow-up carries the returned UUID and number:

```json
{"question":"option 1","title":"Example Book","continuation_id":"<returned UUID>","choice":1}
```

The stored title, author and format remain authoritative on follow-up. Simple
numeric replies such as `1` or `option 1` also work if `choice` is omitted. Choices
expire after 15 minutes, are bound to the configured server/account identity, and
are consumed atomically before evaluation/submission. Movie/TV/book continuation
IDs cannot be interchanged. Invalid conversational selections retain their ID.
The library and source revision are checked again before submission.

Search is bounded to four connections, two advertised searches per connection,
five catalog pages per connection, and 20 offers. Partial searches and limits are
reported; a result is never asserted to be a unique edition. Title phrase and
optional author filters narrow choices; this is not ISBN/edition equivalence.
Library duplicate detection uses normalized exact title, optional author and
format. It does not infer that differently named editions are equivalent. NZB and
Torrent are container labels, not verified ebook formats: they may be selected
explicitly in a generic request but never satisfy a specified EPUB/PDF/MOBI filter.
Only opaque tokens reach NextGen; the adapter does not fetch source/download URLs.

## Acknowledgements and durable state

With `CWNG_AUTO_REQUEST=false`, selection returns `submitted=false`, reason
`dry_run`, and explicitly says no book acquisition job was submitted. The selection
is consumed; start a fresh search for another evaluation.

With the flag enabled, exactly one POST creates a job using the continuation UUID
as NextGen's idempotency key. A valid HTTP 202 acknowledgement reports job ID and
state, including approval/selection states. This is the software's endpoint;
download and import operations belong to NextGen and downstream services.

An additive `book_request_journal` table uses the existing SQLite path
`SEERR_REQUEST_DB`. Its durable claim is written before POST. Re-selecting the same
source/publication/offer identity returns its previously recorded job rather than
posting again. A timeout, ambiguous HTTP outcome or malformed acknowledgement
returns `submitted=null` and retains the claim. No automatic POST retries or job
polling occur. Inspect NextGen before resolving an uncertain claim; deleting the
journal removes duplicate protection. A definite rejection allows a new explicit
search/selection attempt. A recorded job's state is its acknowledgement snapshot,
not a later status check. Keep this database persistent and shared across workers.

## Validation and deployment

Backend checks (Python 3.14):

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SEERR_AUTO_REQUEST=false .venv/bin/python -m pytest tests -q
.venv/bin/python -m planelocket_agent.integrations.calibre_web --check
```

The second command performs read-only login/library/capability checks and prints
safe counts, library mode and source readiness, never credentials or cookies.
No dependency changes are required. Tests exercise real loopback cookie/CSRF
transport, redirect refusal, bounded/invalid responses, session expiry, explicit
selection, independent policy, stale choices, journal deduplication and uncertainty.
HA tests cover registered schemas, dispatch, transport and existing tools.

Before updating Kvasir, back up the shared SQLite database using SQLite's backup
API and retain a reviewed commit. Update the backend, run tests/check, and restart
`planelocket-ai.service`. Back up Frigg's component directory, then copy both
`homeassistant/custom_components/planelocket_ai/client.py` and `llm_api.py` into
`/config/custom_components/planelocket_ai/`, run `ha core check`, and restart HA.
Start a fresh HAL conversation, retaining both Assist and PlaneLocket AI APIs.

Validate a known library title through `search_books`, then a source offer and
numbered choice with the book flag false. Enable book submissions only for the
intended live test. If sources/access are unavailable, resolve them in NextGen
first. Check job acceptance in NextGen without asserting download completion.
To roll back, disable only `CWNG_AUTO_REQUEST`, restore the previous backend and
HA files, and restart them. The additive table can remain; do not restore an older
shared database over new movie/TV request records.

## Pinned upstream contracts

- [Session and CSRF endpoints](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/auth.py)
- [Library JSON API](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/books.py)
- [Book Sources API and permission gates](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/acquisition.py)
- [Opaque catalog selections](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/services/acquisition/catalog.py)
