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
python3 cli.py audit                      # funnel from 48,979 down to a safe list
python3 cli.py sendlist --tier engaged    # count only
python3 cli.py sendlist --tier engaged --out lists/send.csv
python3 cli.py sendlist --tier safe --tag "weekly newsletter subscriber" --out lists/nl.csv
```

Three tiers. `safe` and `engaged` are both narrowings of the mailable pool, and
`engaged` is the default:

| Tier | Meaning | Size |
| --- | --- | --- |
| `safe` | mailable, minus every suppression tag | 34,621 |
| `engaged` | `safe` + carries at least one engagement tag (default) | 10,505 |
| `validated` | `safe` + address confirmed deliverable by a prior send | **0 — refuses to run** |

`validated` is not usable in this location. **No contact has
`validEmail == true`** — the field is set only after GHL has itself sent to an
address, and that history is absent here. The tier therefore matched nothing
while looking like a successful, unusually cautious result, so
`sendlist --tier validated` now refuses and exits non-zero instead of writing a
header-only CSV.

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
Statuses observed live in this location are `inactive` (off), `active` (on) and
`permanent` (on, set by a hard opt-out such as an SMS STOP keyword). The Email
channel currently uses only `active`/`inactive`, but SMS and RCS both carry
`permanent` here, so Email can acquire it. `MAILABLE` excludes both on-statuses.

Exclusion is written as `not_eq`, never as `eq "inactive"`, and that detail is
load-bearing. **Verified live: `eq` on a status value the location does not
currently use matches every contact rather than none.** `Email.status == "inactive"`
returns all 48,979 records, as do `"temporary"` and `"pending"`. A guard phrased
as a positive assertion would therefore stop filtering silently. `not_eq` is
exact — `eq("active")` and `not_eq("active")` sum to the full contact count.

**3. Suppression also lives in tags.** Contacts carrying a suppression *tag*
that no DND field reflects, counted within the mailable pool:

| Count | Tag |
| ---: | --- |
| 8,749 | `do not email` |
| 8,102 | `never send` |
| 1,044 | `soft bounce` |
| 781 | `complainer` |
| 636 | `remove tag` |
| 303 | `spamtrap` |
| 211 | `remove from bootcamp` |

(Counts overlap heavily; removing all eleven suppression tags drops the mailable
pool by 12,641.) `spamtrap` and `complainer` are the dangerous ones — mailing
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

The two pools as measured on 2026-07-26: **10,505** proven core (engaged) plus
**24,116** recovered, for a full pool of **34,621**. The recovered side is more
than twice the size it was, which is the drift flagged in *Account snapshot*
arriving in the ramp — a bigger pool here means more steps, not bigger ones, so
the ramp itself stays safe as long as `--start` still reflects real send volume.

Pass the verifier's bad verdicts via `--exclude-file` until they are tagged in
GHL. No filter can see them before then.

## Reactivation

```bash
python3 cli.py reactivation                      # cohort counts
python3 cli.py reactivation --out-dir lists/     # write both CSVs
```

Produces two files:

- **`verify-candidates.csv`** (3,179 addresses) — suppressed by a *delivery
  failure* with no opt-out of any kind on record. These are the only contacts it
  is appropriate to send to a verification service.
- **`NEVER-UPLOAD.csv`** (8,981 addresses) — consent withdrawn: global DND,
  email-channel DND at any on-status, or a `do not email` / `complainer` /
  `spamtrap` tag.

The never-upload figure fell from 14,982 to 8,981 between snapshots. That is the
same email-channel DND drop flagged under *Unexplained drift* above, seen from
the other side: contacts leaving the DND set leave this list too. Re-read that
section before treating the smaller exclusion list as good news.

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

## Resolved: `never send` vs `validEmail`

The previous snapshot recorded 3,570 contacts with `validEmail == true`, of
which 99% were tagged `never send`, and asked whether the tag had been applied
too broadly. **The question cannot be answered from `validEmail`, because that
field is now empty.** Live on 2026-07-26: 0 contacts have `validEmail == true`,
49 have it `false`, and the other 48,930 have no value at all. There is no
validated pool left to intersect with anything.

Two consequences, both handled in code:

- the `validated` send tier matches nothing and now refuses to run
- `reactivation`'s "already recorded bad" cohort is down to **3 contacts**, so
  it no longer removes anything meaningful from a paid verification run. A
  near-zero figure there means GHL has no delivery history to answer with, not
  that the candidate list is clean. `reactivation` prints that caveat when it
  detects the field is unpopulated.

### What the tag overlap actually shows

Measured directly instead, `never send` is *not* redundant with `do not email`:

| | Count |
| --- | ---: |
| `never send` | 8,176 |
| `do not email` | 8,766 |
| both | 5,829 |
| `never send` only | 2,347 |
| `do not email` only | 2,937 |

Of the 2,347 suppressed by `never send` alone, 2,144 are otherwise mailable and
carry no other suppression tag — and **936 of those carry an engagement tag**,
meaning they have opened or clicked something. That is the population dropping
`never send` would release, and the engagement share is the reason not to drop
it casually: a tag applied to people who were demonstrably interacting is more
likely deliberate than accidental.

This is now a business question rather than a data one, and the data cannot
settle it: whoever applied `never send` knows what it meant. Until that is
established it stays in `SUPPRESSION_TAGS`, which is the conservative default —
the cost of keeping it is 2,144 unmailed contacts, and the cost of removing it
wrongly is mailing people who asked not to be mailed.

## Account snapshot

Verified live against the API on 2026-07-26. The 2026-07-25 column is the
previous snapshot, kept because some of the movement needs explaining:

| | 2026-07-25 | 2026-07-26 |
| --- | ---: | ---: |
| Contacts | 48,978 | 48,979 |
| Has an email address | — | 47,494 |
| Mailable (email present, both DND flags off) | 39,983 | **47,262** |
| Sendable (mailable, minus suppression tags) | 28,856 | 34,621 |
| Engaged (sendable, with an open or click) | 10,752 | 10,505 |
| Recovered (sendable, no engagement tag) | — | 24,116 |
| Global `dnd == true` | — | 148 |
| Email-channel DND on | 3,700 | **227** (84 with `dnd` false) |
| `validEmail == true` | 3,570 | **0** |
| Tags | 544 | 561 |
| Custom fields | 278 | 226 |
| Workflows | 366 (342 draft, 24 published) | token lacks the scope |

Workflow figures could not be re-verified — that endpoint is out of scope for
the current token. Across 16 past events the live show rate was 27.5% on 4,171
registrations, and 3,269 no-shows were recovered at 22.2% by replay.

### ⚠️ Unexplained drift — worth checking in the GHL UI

Contact count moved by one, but three suppression-relevant figures moved a long
way in a single day, all in the direction of *more* contacts being mailable:

- **email-channel DND fell from 3,700 to 227.** If the earlier figure was
  correct, roughly 3,500 contacts who were email-suppressed no longer are.
  Those are unsubscribes, and they are now inside the mailable pool.
- **`validEmail` went from 3,570 true to none at all.**
- **custom fields fell from 278 to 226.**

This tooling only reads, so it did not cause any of it, and it cannot see
history to prove what happened — a bulk edit, an import, a field reset and an
inaccurate earlier snapshot are all consistent with what is visible now. It
matters because the mailable pool grew by 7,279 without anyone opting in.

**Do not treat the growth in `sendable` as new reach until this is explained.**
Tag-based suppression is unaffected and still removes 12,641 contacts, so
`sendlist` remains the safe path; the risk is specifically that DND-based
consent signals were lost. Check the location's audit log before the next send.

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
