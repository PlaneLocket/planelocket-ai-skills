# Book lookup through CWNG; acquisition through LazyLibrarian

HAL's `search_books` reads the Calibre-Web NextGen library. `acquire_book` checks
that library and LazyLibrarian, resolves a bibliographic book, and requests its
**ebook** through LazyLibrarian. A single verified match proceeds without another
confirmation; only multiple matches require a numbered clarification. CWNG
acquisition APIs are not used. Downstream searches/downloads/imports remain with the existing stack.

## Private configuration on Kvasir

```dotenv
CWNG_URL=http://10.10.1.20:8083
CWNG_USERNAME=planelocket-ai
CWNG_PASSWORD='private-account-password'
LAZYLIBRARIAN_URL=http://10.10.1.20:5299
LAZYLIBRARIAN_API_KEY=private-full-access-api-key
LAZYLIBRARIAN_AUTO_REQUEST=false
```

Addresses must be origins without paths, queries or embedded credentials. HTTPS is
supported; these configured household addresses use internal HTTP. Keep credentials
in `.env`, never Git or chat. Frigg uses its existing PlaneLocket token; upstream
credentials stay on Kvasir. No dependency changes are needed.

CWNG uses its dedicated reader account, session cookies and CSRF login. It needs
library visibility, not administrator/edit/upload/delete/Book Sources privileges.
The adapter allows only library/authentication reads and login. It cannot call
CWNG acquisition endpoints. Lookup describes only records visible to that account;
acquisition requires its `monolibrary` view for the library check.

LazyLibrarian needs **Enable API** and an **API Full Access key**. The read-only key
cannot add/queue books or read the limited configuration fields used for readiness
checks. Full access is broad upstream authority; this adapter exposes only fixed
commands and fields. The API key goes in POST form data, never the request URL.
Redirects are refused, responses bounded and errors sanitized.

`LAZYLIBRARIAN_AUTO_REQUEST` defaults to false, independently of
`SEERR_AUTO_REQUEST`. Keep it false during rollout. Existing movie/TV acquisition
may remain enabled. `CWNG_AUTO_REQUEST` is unused and may be removed from `.env`.
No CWNG Book Sources configuration is needed for this integration.

## API and conversation

The existing backend bearer token protects both routes:

```http
POST /books/search
{"query":"Example Author"}

POST /books/acquire
{"question":"Get Example Book by Example Author","title":"Example Book","author":"Example Author"}
```

`query` is up to 500 characters. Search returns visible library matches, formats,
count and completeness. HAL receives at most 25 records; omitted counts are
explicit. It never adds or queues a book or calls LazyLibrarian. This is library
lookup, not external bibliography research.

Acquisition requires separate `question` (up to 2000 characters) and `title` (up
to 500), with optional `author` (up to 300). The backend checks exact normalized
title and optional author against CWNG files, then LazyLibrarian's inventory.
Skipped inventory records can be requested; Wanted/Snatched records are already
requested; Have/Open records are treated as owned. Ignored and unknown statuses
require review in LazyLibrarian rather than being silently overridden.

If no local LazyLibrarian record matches, `findBook` uses its configured metadata
source. Returned source/book IDs remain private backend state. The backend filters
title/author and, when clarification is needed, presents numbered book choices
with publication date, ISBN and language when supplied. These identify
bibliographic records, not verified provider releases or downloadable formats.
A single usable exact title/author match proceeds through fresh checks and policy
without another confirmation. This does not assert globally unique edition identity.
Multiple matches return a numbered clarification:

```json
{"question":"option 1","title":"Example Book","continuation_id":"<returned UUID>","choice":1}
```

"Get <book> by <author>" is sufficient authorization: HAL should call `acquire_book`
directly, without asking whether to request it or doing a preliminary library search.
The tool already checks ownership and existing requests. Library questions such as
"Do I have <book>?" use `search_books` and never acquire it. The book flag enables
writes; it does not introduce another user confirmation.

For an ambiguous result, simple numeric replies also work without `choice`.
Whenever a structured `choice` is sent, the returned `continuation_id` is mandatory.
Stored selected title/author
remain authoritative. IDs expire after 15 minutes and are bound to the CWNG
account and LazyLibrarian address/key. Changed metadata-source settings, missing or
changed book identity, cross-media IDs and consumed/expired IDs are rejected.
Invalid conversational choices retain their ID. Valid evaluation consumes it
atomically, including dry runs. Old CWNG-acquisition selections are not reusable.

This initial integration handles **ebooks only**. It does not request audiobooks,
whole authors/series, magazines, or a particular download format. If the user
requires EPUB/PDF/MOBI, HAL passes `format` and the backend explicitly reports that
per-request enforcement is unsupported (or reports already-owned matching files).
It never silently drops the requirement or rewrites LazyLibrarian's global format
preferences. Provider and download-client configuration stays in LazyLibrarian.

## Submission and acknowledgement

Before writing, the backend rechecks CWNG and LazyLibrarian inventory. New external
records are revalidated against a fresh metadata search. Adding an ebook is blocked
if LazyLibrarian's **new audiobook status** (`NEWAUDIO_STATUS`) is not Skipped or
Ignored: `addBook` uses server defaults and must not implicitly request an audiobook.
This gate does not change that setting. Existing Skipped records need no addBook
and only their ebook status is modified.

With `LAZYLIBRARIAN_AUTO_REQUEST=false`, evaluation returns `submitted=false`,
reason `dry_run`, and explicitly says no ebook request was submitted. No addBook,
queueBook or searchBook commands run. Library/metadata/configuration reads can run.

When enabled, the adapter uses `addBook&id=...&source=...&wait=1` only if the record
is absent, verifies the inserted identity, then uses `queueBook&id=...&type=eBook`
if needed. It never queues AudioBook or changes existing audiobook status. Finally
the supported `getAllBooks` inventory API verifies that exact book's title, author
and Wanted state (or advancement to Snatched/Have/Open). The pinned build defines
a Python `_getbook` method but does not register `getBook` as an API command; the
adapter never calls that unsupported command. Unknown-command and read-only-key
permission errors are reported separately from invalid credentials. A bare `OK` is insufficient. The result reports the book ID and verified
state, not an invented job ID or a completed download. LazyLibrarian's configured
scheduler handles Wanted books; this integration does not force a search, download
or import. Adding a record follows LazyLibrarian's metadata/default settings.

There is no upstream transaction or idempotency key for these commands. An additive
`book_request_journal` in `SEERR_REQUEST_DB` reserves each LazyLibrarian target/book
before writes. It blocks duplicate submissions across conversations/workers. New
choices cannot bypass a submitting/uncertain claim. Successful requests keep a
snapshot of acknowledgement state; they are not polled later. The internal journal
`job_id` column holds the LazyLibrarian book ID, not a downloader job ID.

A lost acknowledgement, partial add/queue, or failed final verification returns
`submitted=null`; inspect LazyLibrarian before retrying. Writes are never retried
automatically and no rollback changes are issued. A definite rejection before any
accepted mutation permits a fresh explicit selection. After recorded success, a
later intentional re-request must be handled in LazyLibrarian. Keep this database
persistent and shared across workers; deleting it removes local duplicate guards.

Checks and writes are separate remote calls: an administrator or scheduler can
change records/defaults concurrently. This adapter cannot make LazyLibrarian's API
atomic. Existing status checks and durable claims reduce duplicate writes without
claiming a cross-service transaction.

## Bounds and limitations

CWNG library pagination is capped at 500 records; unstable counts, repeated IDs or
missing pages mark it incomplete. LazyLibrarian `getAllBooks` has a limit but no
pagination/total contract: the adapter requests 10001 records and refuses absence
claims above 10000, or on duplicate IDs. An 8 MiB response cap can also refuse large
inventories. Acquisition blocks if either check is incomplete. External metadata
searches are bounded to 2000 returned records and 20 displayed choices; completeness
is not asserted. Unusable external suggestions are skipped individually, with
received/skipped counts in the result and skipped counts in the answer. Malformed
response envelopes and size/count limits still fail the search; a zero-match
result does not prove that the book is unavailable. Inventory validation remains
strict, and a selected book must remain valid in a fresh metadata search before
addition. Timeouts report `ll_timeout`, separately from connection failures.
Narrow the title/author when no exact normalized match is returned.
Different spellings/editions/ISBNs are not inferred equivalent. Book/source metadata
is untrusted data, never authorization or instructions.

## Validation and deployment

The contracts were inspected at CWNG **v4.1.52** and LazyLibrarian **a0fe7646**
(LinuxServer `a0fe7646-ls379`, build 2026-10-23). Live credentials stay on Kvasir,
so authenticated transport/readiness is a deployment check.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 SEERR_AUTO_REQUEST=false .venv/bin/python -m pytest tests -q
.venv/bin/python -m planelocket_agent.integrations.calibre_web --check
.venv/bin/python -m planelocket_agent.integrations.lazylibrarian --check
```

The two checks are read-only. They report safe library counts/mode and LL version,
metadata source, new-book/audio defaults and the book switch. They do not queue a
book or force a search. Tests cover real loopback session/CSRF and form transport,
plain/JSON responses, redirected/error responses, exact identity/status checks,
independent policy, partial writes, journal claims, and HA schema/dispatch/transport.

Before updating Kvasir, back up the shared SQLite database using SQLite's backup
API and retain a reviewed commit. Update the backend, run tests/checks, and restart
`planelocket-ai.service`. Back up Frigg's component directory, copy both `client.py`
and `llm_api.py` from `homeassistant/custom_components/planelocket_ai/` into
`/config/custom_components/planelocket_ai/`, run `ha core check`, and restart HA.
Start a fresh HAL conversation with Assist and PlaneLocket AI selected.

Validate a known CWNG title with `search_books`; then validate an explicit book
request with the LL switch false. A single match should reach dry-run without
confirmation; multiple matches should ask for clarification. Enable book requests
only for the intended live test. If an earlier request returned an uncertain result, inspect its existing
LazyLibrarian status first; do not blindly resubmit or clear the journal. The acceptance criterion is the correct book's verified LazyLibrarian
status. Downloads/imports remain outside this software deployment validation.

Rollback: disable only `LAZYLIBRARIAN_AUTO_REQUEST`, restore the previous backend
and HA files, and restart. The additive table can remain. Do not restore an old
shared database over new movie/TV request records.

## Upstream contracts

- [CWNG library API](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/books.py)
- [CWNG session/CSRF API](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/auth.py)
- [LazyLibrarian API commands and responses](https://github.com/LazyLibrarian/LazyLibrarian/blob/a0fe7646/lazylibrarian/api.py)
- [LazyLibrarian configuration defaults](https://github.com/LazyLibrarian/LazyLibrarian/blob/a0fe7646/lazylibrarian/configdefs.py)
