# GHL-Claude

Tooling for the **University Of Options** GoHighLevel location, built on the
v2 API with a private integration token.

## Setup

Two environment variables, already set in this environment:

| Variable | Purpose |
| --- | --- |
| `GHL_API_KEY` | Private integration token (`pit-…`). Legacy v1 keys are rejected. |
| `GHL_LOCATION_ID` | The sub-account this tooling is scoped to. |

The token is never read from a file or passed as an argument, and `.gitignore`
excludes credentials and exported CSVs (which contain personal data).

```bash
python3 cli.py info
python3 tests.py    # offline, no network, no pytest
```

### ⚠️ The configured location is not the one this work documents

`GHL_LOCATION_ID` is currently **`U23Jnu7rscfzAOUmSevW`**. Every prior session,
the handoff sheet and the figures below were produced against **University Of
Options — `IyorbIIbJLsMLaqy8j1P`**. These are different GoHighLevel
sub-accounts, and the current token cannot reach the second one at all:

```
POST /contacts/search  locationId=IyorbIIbJLsMLaqy8j1P
  -> 403 {"message":"The token does not have access to this location"}
```

They are easy to mistake for one another — both hold roughly 48,978 contacts and
share tag names like `never send`, `do not email` and `spamtrap` — but none of
the tags this project created exist in the configured one. `current email list`,
`email batch 1`–`5` and `verified bad` are all absent, so the ZeroBounce
verification and the volume-ramp tagging are not present there.

**Any figure measured in this environment describes `U23Jnu7rscfzAOUmSevW`, not
the account the send plan is for.** Fix the credentials before acting on a count.

### Token scopes

A private integration token is issued with a chosen set of scopes, and the
contact scopes are separable from the rest. The token currently in this
environment can read contacts and tags but not locations, workflows or emails,
so those endpoints answer `401 The token is not authorized for this scope`.

Everything that builds a list keeps working, because all of it runs on
`POST /contacts/search`. `info` prints `unavailable (token lacks this scope)`
for the parts it cannot reach rather than failing whole; `workflows` and
`schedules` fail with an error naming the fix. To restore them, add the
`locations.readonly`, `workflows.readonly` and `emails.readonly` scopes in
**Settings > Private Integrations** and re-issue the token.

## Commands

All commands here are **read-only**. Nothing sends an email, edits a contact,
or enrols anyone in a workflow.

```bash
python3 cli.py info                       # account summary
python3 cli.py tags --search newsletter   # find tags
python3 cli.py workflows --status published
python3 cli.py schedules                  # existing email campaign schedules
python3 cli.py count  --tag "weekly newsletter subscriber" --mailable
python3 cli.py export --tag "weekly newsletter subscriber" --mailable \
                      --out lists/newsletter.csv
```

`--tag` repeats to mean OR. `--mailable` drops contacts with no email address
and contacts with DND set — but see the warning below, it is **not** sufficient
on its own for a send list.

### Building a send list

```bash
python3 cli.py audit                      # funnel from all contacts to a safe list
python3 cli.py sendlist --tier engaged    # count only
python3 cli.py sendlist --tier engaged --out lists/send.csv
python3 cli.py sendlist --tier safe --tag "weekly newsletter subscriber" --out lists/nl.csv
```

Three tiers. `safe` and `engaged` are both narrowings of the mailable pool, and
`engaged` is the default:

| Tier | Meaning | UOO | configured acct |
| --- | --- | ---: | ---: |
| `safe` | mailable, minus every suppression tag | 28,856 | 34,621 |
| `engaged` | `safe` + carries at least one engagement tag (default) | 10,752 | 10,505 |
| `validated` | `safe` + address confirmed deliverable by a prior send | 23 | 0 |

`validated` is not usable in either account, for different reasons. In UOO it is
degenerate — 99% of contacts with `validEmail == true` also carry `never send`,
so intersecting them leaves 23. In the configured account **no contact has
`validEmail == true` at all**, so it matches nothing while looking like a
successful, unusually cautious result.

`sendlist --tier validated` therefore checks first and refuses when the field is
unpopulated, exiting non-zero rather than writing a header-only CSV. That guard
is about the field being absent, not about which account is configured.

Note that `engaged` and `validated` are alternative narrowings of `safe`, not
successive ones. `audit` used to print all five figures in a single column,
which read as one funnel and made the safe list look an order of magnitude
smaller than it is.

## ⚠️ Three suppression traps

**1. The global DND flag misses per-channel email DND.** GoHighLevel tracks DND
per channel in `dndSettings`, separately from the global `dnd` boolean. A
contact can be email-suppressed there while `dnd` is false, and a filter on
`dnd` alone would mail every one of them. `MAILABLE` checks both.

**2. Per-channel DND is not a boolean, and `"active"` is not the only "on".**
Statuses observed are `inactive` (off), `active` (on) and `permanent` (on, set
by a hard opt-out such as an SMS STOP keyword). Email was seen using only
`active`/`inactive`, but SMS and RCS both carry `permanent`, so Email can
acquire it. `MAILABLE` excludes both on-statuses. This is defensive rather than
load-bearing today — it costs nothing and closes the gap wherever it appears.

Exclusion is written as `not_eq`, never as `eq "inactive"`, and that detail *is*
load-bearing. **Verified live: `eq` on a status value the location does not
currently use matches every contact rather than none** — `Email.status ==
"inactive"` returned the entire contact list, as did `"temporary"` and
`"pending"`. A guard phrased as a positive assertion would stop filtering
silently. `not_eq` is exact: `eq("active")` and `not_eq("active")` sum to the
full contact count.

(Both observations come from `U23Jnu7rscfzAOUmSevW`. They are statements about
how the GHL API treats these operators, which is not location-specific, but the
per-channel status *values* in UOO have not been re-checked.)

**3. Suppression also lives in tags.** In UOO, 11,127 contacts carry a
suppression *tag* that no DND field reflects:

| Count | Tag |
| ---: | --- |
| 7,426 | `never send` |
| 7,421 | `do not email` |
| 956 | `soft bounce` |
| 591 | `remove tag` |
| 539 | `complainer` |
| 268 | `spamtrap` |

(Counts overlap; 11,127 is the de-duplicated total.) `spamtrap` and `complainer`
are the dangerous ones — mailing
those is the fastest route to a blocklisting. Use `sendlist`, not
`export --mailable`, for anything that will actually be sent.

The tag list is hand-curated in `ghl/sending.py` and does not update itself. A
new suppression tag added in the GHL UI will not be honoured until it is added
there.

## Weekly webinar send plan

```bash
python3 cli.py weekly --event "7/24"
python3 cli.py weekly --event "7/24" --out-dir lists/week-07-24
```

The webinar runs at a fixed time, so every send slot is knowable in advance and
can be a scheduled broadcast. No workflow is required, which sidesteps the fact
that the API cannot create workflows at all.

WebinarJam sends its own registrant reminders at 48h, 24h, 1h and 15min, each
carrying that registrant's unique join link. Duplicating those in GHL would
double-message the people most likely to attend, and GHL cannot reproduce the
per-registrant link. So the default plan cedes pre-event Track A to WebinarJam:

| Slot | Track | Audience | Sent by |
| --- | --- | --- | --- |
| mon-invite-1 | B | engaged list, minus registrants | GHL |
| tue-invite-2 | B | engaged list, minus registrants | GHL |
| *48h / 24h / 1h / 15min* | A | registrants | **WebinarJam** |
| thu-last-call | B | engaged list, minus registrants | GHL |
| thu-replay | post | no-shows | GHL |
| fri-replay-final | post | no-shows | GHL |
| fri-attendee-next | post | attendees | GHL |

GHL keeps exactly what WebinarJam does not do: persuading people who have not
registered, and everything after the event ends. Pass `--reminders ghl` to add
the registrant slots back, but only if WebinarJam's reminders are disabled or
landing in spam -- with both live, registrants receive two sets.

Track B wants persuasion rather than logistics and must have registrants removed
from every send, so it never collides with what WebinarJam is sending.

A slot whose tag does not exist counts 0; a slot whose count *fails* is reported
as `FAILED` with the reason, and `weekly` exits non-zero. Those two used to be
merged into one "tag missing" label, which meant an API failure could quietly
remove a send from the week's plan.

Slots that share an audience are exported once rather than as byte-identical
files. **Re-export Track B close to send time**: the export is a snapshot, and
anyone who registers mid-week must drop out of the unregistered list.

## Volume ramp

```bash
python3 cli.py rollout --step 2
python3 cli.py rollout --step 2 --out lists/step2.csv \
                       --exclude-file lists/ACTION-hard-exclude.csv
```

Verification settled deliverability for 20,010 contacts but not whether people
who have heard nothing since 2024 still want to hear from you. That is answered
by complaint rate, and complaint rate rather than bounce rate is what damages a
domain that has already been rebuilt once.

So the recovered pool is added in steps of +25%. Each step holds the proven core
constant and adds a bounded slice, newest first: the more recently someone opted
in, the more likely they are to recognise the sender.

The pools have not been measured in UOO since the ramp was written. In the
configured account they are 10,505 core plus 24,116 recovered, but that is a
different sub-account and should not be used to size a UOO send.

A larger recovered pool means more steps, not bigger ones, so the ramp stays
safe either way as long as `--start` reflects real proven send volume.

Pass the verifier's bad verdicts via `--exclude-file` until they are tagged in
GHL. No filter can see them before then.

## Reactivation

```bash
python3 cli.py reactivation                      # cohort counts
python3 cli.py reactivation --out-dir lists/     # write both CSVs
```

Produces two files:

- **`verify-candidates.csv`** (3,036 addresses in UOO) — suppressed by a
  *delivery failure* with no opt-out of any kind on record. These are the only
  contacts it is appropriate to send to a verification service.
- **`NEVER-UPLOAD.csv`** (14,982 addresses in UOO) — consent withdrawn: global
  DND, email-channel DND at any on-status, or a `do not email` / `complainer` /
  `spamtrap` tag.

Run against the configured account these come out at 3,179 and 8,981, which is
a different sub-account rather than a change in UOO.

The split matters because a hard bounce is a fact about the recipient's mailbox
and survives a change of sending domain, whereas a reputation block is a fact
about the sender and does not. The 2023-2025 failure rates (62-100%) are a
reputation signature, so many of those "failures" were valid mailboxes refusing
a poisoned sender.

An opt-out is a third case and the strict one: consent withdrawal is permanent
and domain-independent. A verifier will happily return "valid" for an address
you are not permitted to mail, and that green tick is exactly how such an
address finds its way back into a send.

### Deduplication is by address, not contact id

This location contains duplicate contact records for the same person. Ten
addresses initially appeared on *both* lists: one record carried the opt-out
while a duplicate did not, so the clean duplicate passed the candidate filter on
its own merits. Consent attaches to the address, not the record, so the export
filters `verify-candidates.csv` against every suppressed address before writing.
The two files are verified to share zero addresses.

## Still open: `never send` vs `validEmail`

Of the 3,570 UOO contacts GHL had confirmed deliverable and that pass `MAILABLE`,
**3,538 (99%) are tagged `never send`** and 2,558 (72%) are tagged
`do not email`. Either the tag was applied more broadly than intended, or the
validated pool is genuinely a historical list that was later suppressed
wholesale. Worth confirming before treating `never send` as a permanent
exclusion, since it is the single largest suppression set.

**This has not been resolved.** An attempt to settle it on 2026-07-26 measured
the wrong sub-account — `U23Jnu7rscfzAOUmSevW`, where `validEmail` is empty and
the tag overlap is different — so those findings say nothing about UOO and have
been removed. Re-running it needs a token with access to `IyorbIIbJLsMLaqy8j1P`.

The question to answer there is not really about `validEmail`, which only records
whether GHL has delivered to an address before. It is how much of `never send`
is *not* already covered by `do not email`: the contacts carrying `never send`
alone, otherwise sendable, and especially any among them with engagement tags.
A suppression tag sitting on people who were demonstrably opening and clicking
is the case that most needs a human to confirm what the tag meant.

Until then `never send` stays in `SUPPRESSION_TAGS`. That is the conservative
default: the cost of keeping it wrongly is unmailed contacts, and the cost of
dropping it wrongly is mailing people who asked not to be mailed.

## Account snapshot

Two different sub-accounts, kept side by side because it is otherwise very easy
to read a number from the wrong one. The left column is the account this project
is for; the right is the one the current credentials actually reach.

| | UOO `IyorbIIbJLsMLaqy8j1P` (2026-07-25) | configured `U23Jnu…` (2026-07-26) |
| --- | ---: | ---: |
| Contacts | 48,978 | 48,980 |
| Has an email address | — | 47,494 |
| Mailable (email present, both DND flags off) | 39,983 | 47,262 |
| Sendable (mailable, minus suppression tags) | 28,856 | 34,621 |
| Engaged (sendable, with an open or click) | 10,752 | 10,505 |
| Recovered (sendable, no engagement tag) | — | 24,116 |
| Global `dnd == true` | — | 148 |
| Email-channel DND on | 3,700 | 227 (84 with `dnd` false) |
| `validEmail == true` | 3,570 | 0 |
| Tags | 544 | 561 |
| Custom fields | 278 | 226 |
| Workflows | 366 (342 draft, 24 published) | token lacks the scope |

**The two columns are not a before and after.** They are separate
sub-accounts measured a day apart, and nothing in the right-hand column says
anything about the left. The UOO figures have not been re-verified since
2026-07-25, because the current token cannot reach that location.

Across 16 past events the live show rate was 27.5% on 4,171 registrations, and
3,269 no-shows were recovered at 22.2% by replay. **Every one of the 75
webinar-related workflows is in `draft`** — no reminder, no-show follow-up or
replay automation is running.

### Note on a retracted warning

An earlier revision of this file read the two columns as one account changing
overnight and flagged it as lost consent — roughly 3,500 unsubscribes apparently
re-entering the mailable pool. **That was wrong**, and the tell was available at
the time: the contact counts match to within two, which is a coincidence no bulk
edit produces. The two locations are near-copies of each other, so a same-day
comparison looked like drift.

Worth keeping in mind whenever a figure here moves unexpectedly: check which
`GHL_LOCATION_ID` produced it before concluding the account changed.

## What the API can and cannot do

Verified by probing the live endpoints:

| Goal | Status |
| --- | --- |
| Targeted lead lists | **Full support.** `POST /contacts/search` handles nested AND/OR groups, tag/date/field filters, and cursor pagination. |
| Bulk email scheduling | **Supported.** `/emails/schedule` and `/emails/builder` respond; campaign create/update/schedule endpoints exist. |
| Enrolling contacts in workflows | **Supported.** `POST /workflows/{id}/contacts/{contactId}`. |
| **Creating or editing workflows** | **Not possible.** Workflows are read-only in the public API — there is no endpoint for triggers, conditions, or actions. `POST /workflows/` returns 404. This is a [known open feature request](https://ideas.gohighlevel.com/apis/p/api-endpoints-post-put-del-for-workflows), not a gap in this tooling. |

Workflows still have to be built in the GHL UI. What is automatable is
everything around them — deciding who belongs in one and enrolling them in bulk.

## API behaviour worth knowing

- **Rate limits:** 100 requests per 10s burst, 200,000/day. `GHLClient`
  self-throttles below the burst ceiling and retries on 429/5xx with backoff.
- **A 401 means two unrelated things, and only one of them is permanent.**
  Slow queries return `401 {"message":"Command timed out"}` rather than a
  timeout status, and succeed on a retry. A token that is expired or missing a
  scope returns `401 {"message":"The token is not authorized for this scope."}`,
  which no amount of retrying fixes. The status code cannot tell them apart, so
  the client classifies on the body: it retries the timeout with backoff, and
  raises `GHLScopeError` — carrying the fix — for the scope failure.

  This was previously documented as working but was not implemented: `request()`
  retried only 429 and 5xx, so a timed-out 401 aborted the run. That mattered
  most on exactly the calls it hits — long `search_contacts` pagination, where
  it killed an export part-written.
- **Pagination uses the `searchAfter` cursor**, not offsets; offset paging is
  capped server-side and silently truncates results.
- **Date filters run in the location's timezone, but `dateAdded` is returned in
  UTC.** A contact stamped `2026-07-25T06:03Z` is 23:03 on 2026-07-24 in
  America/Los_Angeles and will not match a range starting 2026-07-25. Segment by
  local dates rather than by the UTC timestamps that appear in CSV exports.

## Layout

```
ghl/client.py        authenticated client: throttling, retries, 401 classification
ghl/segments.py      filter helpers, mailability guard, CSV export
ghl/sending.py       suppression tags, send tiers, funnel audit
ghl/reactivation.py  verify-vs-never-upload split, address-level consent dedup
ghl/weekly.py        per-webinar two-track send plan
ghl/rollout.py       staged volume ramp
cli.py               read-only command line interface
tests.py             offline tests: no network, no pytest
```

`tests.py` covers the failures that return a plausible answer rather than an
error — a suppression guard that stops matching, a send list emptied by an
unpopulated input field, a slot silently dropped from a send plan. Those are the
ones a live spot-check does not catch.

## Writes

No write path is implemented yet, deliberately. An untested POST against
`/emails/schedule` would reach a real audience of tens of thousands. Write
support should land behind a dry-run default and an explicit confirmation flag.
