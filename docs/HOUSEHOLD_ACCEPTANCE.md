# Household conversation corrections

The live tests exposed an owned book reported missing, an informational TV
follow-up routed into acquisition, calls after a terminal backend outcome, and
unadvertised inventory access. These are acceptance failures despite passing
single-call adapter tests.

## Requirements, ownership and verification

| Requirement | Owner | Automated verification | Live verification still needed |
| --- | --- | --- | --- |
| Natural title-and-author lookup finds the same owned record as author lookup | Backend CWNG client | Combined queries, reversed author names, apostrophes, wrong author, absent book; authenticated loopback inventory and partial scan tests | Actual CWNG records and varied natural wording |
| All supported reads are discoverable without provider rules in HA | Backend capabilities endpoint and skill metadata; generic adapter forwarding | Dispatcher includes books and inventory; backend descriptions appear in HA tool metadata; future descriptions require no adapter edit | HAL calls the lookup for parts instead of denying access |
| Informational follow-ups remain read-only | Backend semantic intent resolution; adapter transports original user text/history | Incorrect acquisition calls with original `yes` after an informational offer are rerouted to investigation; no movie, TV or book acquisition functions run | Actual model intent classifications, including genuine acquisition clarifications |
| Explicit acquisition needs no additional confirmation | Existing backend workflows | Semantic `acquire` enters existing workflow exactly once; existing single-match/journal tests retained | Natural acquisition and ambiguity follow-ups |
| A terminal outcome prevents more automatic household calls that turn | Generic adapter turn state | Sequential and concurrent later calls never reach backend after blocked/uncertain; a new API instance permits a new user turn | HAL behavior with actual chat logs |
| Provider details and workflow policy remain in backend | Backend integration/interaction modules | Existing adapter architecture tests retained; public five tool names and schemas unchanged | Final phrasing stays faithful to backend answer |
| Native Assist remains available during outages | HA API composition | Static fallback when metadata unavailable; native-device outage regression retained | Actual devices, if desired |
| Catalog listings are not claimed as owned seasons; unsupported acquisition is not offered | Backend investigation/capability instructions | Scope instructions supplied by backend; actual ownership tools retained | HAL's final response and backend model reasoning |

## Behavior and boundaries

`GET /capabilities` is authenticated, provider-neutral metadata for clients. HA
loads it with a two-second deadline when preparing a turn and falls back to its
existing static tools on failure. Registration itself remains offline. Capability
descriptions and supported-action instructions live in the backend; the adapter
does not encode provider names, statuses or command rules.

HA copies bounded user/assistant text from Home Assistant's active chat log.
System prompts and tool-result evidence are excluded. The latest user turn is
sent separately as `user_question`, along with up to ten earlier text messages;
the LLM's rewritten tool question cannot replace it. On acquisition routes the
backend uses structured semantic classification against that original context.
A lookup is rerouted to the read-only investigation; an acquisition enters the
existing workflow without another consent step. Unresolved intent attempts no
write. This is intent resolution, not a provider permission policy. Older direct
API clients without the new optional context retain their explicit-intent contract.

This classifier is still a model judgment, not a proof of user intent. Tests mock
its outputs to verify routing, use of original text, and absence of writes; they
do not establish live classification accuracy. The extra inference has a
30-second timeout and can add latency. Transport uncertainty remains terminal.

The generic stop latch is shared by the five PlaneLocket tools within a turn's
API instance. Calls are serialized so a queued call cannot race past a preceding
stop. It returns the original terminal result instead of making another backend
call. The next user turn obtains a new API instance. It does not terminate HAL's
model loop, police unrelated native tools, or force HAL to speak verbatim.

Book lookup reads the visible authenticated catalog and matches normalized words
across title, authors and series, ignoring the connective `by`. This avoids CWNG's
single-string search false negative for title plus author. The existing 500-record,
60-second bounds remain; partial/changing/repeated inventory cannot establish
absence. This is a bounded lookup, not a claim of unrestricted library coverage.
Acquisition's separate exact identity and ownership checks remain unchanged.

## Rollout and remaining acceptance

Deploy backend first, then both adapter files; no new credentials, database
migration, acquisition flags or dependencies are required. Existing HA system
instructions must not route acquisitions through the read-only household tool.

After deployment, use ordinary questions such as “Do I have The Alloy of Law by
Brandon Sanderson?”, “How many SN74AHCT125N chips do I have?”, and “Which seasons
of Foundation do I have?”. Verify tool traces, not merely the spoken answer.
Then exercise an informational follow-up and an explicit acquisition you want.
Do not treat provider acceptance as download completion.

Until live checks pass, natural routing, semantic classifications, evidence-faithful
phrasing, and complete end-to-end acceptance remain unverified. Automated counts
do not replace these checks.
