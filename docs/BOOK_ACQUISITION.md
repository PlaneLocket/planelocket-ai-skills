# Book lookup through CWNG; acquisition through LazyLibrarian

HAL's `search_books` reads the Calibre-Web NextGen library. `acquire_book` checks
that library and LazyLibrarian, resolves a bibliographic book, and requests its
**ebook acquisition search** through LazyLibrarian. Wanted is preparation, not
evidence that a search or download has begun. A single verified match proceeds without another
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
Skipped records are queued as Wanted before search. Existing Wanted records are
eligible for an immediate ebook search without re-adding/re-queueing them.
Snatched records are already in progress; Have/Open records are treated as owned. Ignored and unknown statuses
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
is absent, verifies the inserted identity, and uses `queueBook&id=...&type=eBook`
only if necessary. It verifies the exact ID/title/author and Wanted state through
the supported `getAllBooks` inventory API. Then it invokes
`searchBook&id=...&type=eBook` **without `wait`** to initiate that ebook's background
provider search. It never calls the bulk `forceBookSearch` command or requests
AudioBook. Snatched/owned records are not searched again.

Wanted alone is a wishlist/eligibility state. `submission.submitted=true` for the
new flow means the specific `searchBook` command was acknowledged with `OK`;
`submission.operation` is `searchBook`. It does not establish that a provider found
a release, a downloader accepted it, or a download started/completed. No download
monitoring or completion polling is added. The pinned command returns a definite
rejection when no search methods are enabled. An `OK` is asynchronous acceptance;
background provider failures can still occur in LazyLibrarian.

The pinned build defines a Python `_getbook` method but does not register `getBook`
as an API command; it is never used. Unknown-command, read-only-key permission and
credential errors are distinguished. A previous verification error after queueing
can leave a valid Wanted book; the new flow verifies its state and searches it
without replaying preparation writes.

There is no upstream transaction or idempotency key for these commands. The
existing `book_request_journal` in `SEERR_REQUEST_DB` now uses distinct key
namespaces for preparation and acquisition search, with a separate request ID for
each claim. No database migration or claim deletion is required. Legacy records
only describe add/queue operations and cannot establish search acceptance. A fresh
verified Wanted state permits the first new search without clearing or replaying
an older uncertain preparation claim. If that state cannot be verified, it blocks
search. An uncertain **search** claim remains a strict no-replay guard, even while
the book is Wanted.

A search claim is persisted before its POST. Repeated calls and workers cannot
launch a second acknowledged or uncertain search. A prior acknowledged search is
reported as history, not an active download; later manual search retries can be
performed in LazyLibrarian. A definite rejection (including no enabled methods)
permits a new explicit request after correction. Network errors or ambiguous
acknowledgements return `submitted=null`, preserve the search claim and never
retry automatically. No rollback or downloader-control commands run.

If preparation succeeds but search is rejected or disabled, the response states
that the book is Wanted but no search was accepted. It does not claim complete
acquisition or that no preparation occurred. Keep this database persistent and
shared across workers. Deleting it removes local duplicate guards. The internal
`job_id` column holds the book ID, not a downloader job ID.

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
only for the intended live test. Earlier uncertain preparation can be reconciled
by the existing verified Wanted state without re-adding or re-queueing the book;
do not clear journal claims. A prior uncertain search must not be replayed.
The acceptance criterion is acknowledgement of `searchBook` for the correct ebook,
or a verified already-Snatched/owned result; Wanted alone does not pass.
Downloads/imports remain outside this software deployment validation.

Rollback: disable only `LAZYLIBRARIAN_AUTO_REQUEST`, restore the previous backend
and HA files, and restart. The additive table can remain. Do not restore an old
shared database over new movie/TV request records.

## Upstream contracts

- [CWNG library API](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/books.py)
- [CWNG session/CSRF API](https://github.com/new-usemame/Calibre-Web-NextGen/blob/v4.1.52/cps/api/auth.py)
- [LazyLibrarian API commands and responses](https://github.com/LazyLibrarian/LazyLibrarian/blob/a0fe7646/lazylibrarian/api.py)
- [LazyLibrarian configuration defaults](https://github.com/LazyLibrarian/LazyLibrarian/blob/a0fe7646/lazylibrarian/configdefs.py)
