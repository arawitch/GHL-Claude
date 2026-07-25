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
```

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
python3 cli.py audit                      # funnel from 48,978 down to a safe list
python3 cli.py sendlist --tier engaged    # count only
python3 cli.py sendlist --tier engaged --out lists/send.csv
python3 cli.py sendlist --tier safe --tag "weekly newsletter subscriber" --out lists/nl.csv
```

Three tiers, progressively more conservative:

| Tier | Meaning | Size |
| --- | --- | --- |
| `safe` | mailable, minus every suppression tag | 28,856 |
| `engaged` | `safe` + carries at least one engagement tag (default) | 10,752 |
| `validated` | `safe` + address confirmed deliverable by a prior send | 23 |

`validated` is degenerate here and should not be used: 99% of contacts with
`validEmail == true` also carry the `never send` tag, so intersecting the two
leaves almost nothing. See the note at the end of this file.

## ⚠️ Two suppression traps

**1. The global DND flag misses per-channel email DND.** GoHighLevel tracks DND
per channel in `dndSettings`, where `status == "active"` means DND is ON for
that channel. **3,700 contacts have `dndSettings.Email.status == "active"` while
`dnd` is false** — email-suppressed without the global flag. `MAILABLE` now
checks both; a filter on `dnd` alone would mail every one of them.

**2. Suppression also lives in tags.** 11,127 contacts carry a suppression
*tag* that no DND field reflects:

| Count | Tag |
| ---: | --- |
| 7,426 | `never send` |
| 7,421 | `do not email` |
| 956 | `soft bounce` |
| 591 | `remove tag` |
| 539 | `complainer` |
| 268 | `spamtrap` |

(Counts overlap; 11,127 is the de-duplicated total.) `spamtrap` and `complainer`
are the dangerous ones — mailing those is the fastest route to a blocklisting.
Use `sendlist`, not `export --mailable`, for anything that will actually be sent.

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

Two tracks run in parallel all week, wanting opposite things:

| Slot | Track | Audience |
| --- | --- | --- |
| mon-invite-1 | B | engaged list, minus registrants |
| tue-invite-2 | B | engaged list, minus registrants |
| wed-reminder-24h | A | registrants |
| thu-reminder-1h | A | registrants |
| thu-live-now | A | registrants |
| thu-last-call | B | engaged list, minus registrants |
| thu-replay | post | no-shows |
| fri-replay-final | post | no-shows |
| fri-attendee-next | post | attendees |

Track A wants logistics and tolerates high frequency -- they asked to be there.
Track B wants persuasion and must be mailed less often, with registrants removed
from every send. The segments are mutually exclusive, so nobody receives both
versions of the same message.

Slots that share an audience are exported once rather than as byte-identical
files. **Re-export Track B close to send time**: the export is a snapshot, and
anyone who registers mid-week must drop out of the unregistered list.

## Reactivation

```bash
python3 cli.py reactivation                      # cohort counts
python3 cli.py reactivation --out-dir lists/     # write both CSVs
```

Produces two files:

- **`verify-candidates.csv`** (3,036 addresses) — suppressed by a *delivery
  failure* with no opt-out of any kind on record. These are the only contacts it
  is appropriate to send to a verification service.
- **`NEVER-UPLOAD.csv`** (14,982 addresses) — consent withdrawn: global DND,
  email-channel DND, or a `do not email` / `complainer` / `spamtrap` tag.

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

## Open question: `never send` vs `validEmail`

Of the 3,570 contacts GHL has confirmed deliverable and that pass `MAILABLE`,
**3,538 (99%) are tagged `never send`** and 2,558 (72%) are tagged
`do not email`. Either the tag was applied more broadly than intended, or the
validated pool is genuinely a historical list that was later suppressed
wholesale. Worth confirming before treating `never send` as a permanent
exclusion, since it is the single largest suppression set.

## Account snapshot

Verified live against the API on 2026-07-25:

| | |
| --- | --- |
| Contacts | 48,977 |
| Mailable (has email, DND off) | 43,682 |
| Tags | 544 |
| Custom fields | 278 |
| Workflows | 366 |
| Email templates | 38 |

**5,295 contacts are not mailable** — 1,408 have no email address and 3,888
have DND enabled (one contact is both). Any bulk send must exclude them, which
is what `--mailable` does.

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
- **Slow queries return `401 {"message":"Command timed out"}`** rather than a
  timeout status. This is transient and misleading — it is not an auth failure.
  The client retries it.
- **Pagination uses the `searchAfter` cursor**, not offsets; offset paging is
  capped server-side and silently truncates results.
- **Date filters run in the location's timezone, but `dateAdded` is returned in
  UTC.** A contact stamped `2026-07-25T06:03Z` is 23:03 on 2026-07-24 in
  America/Los_Angeles and will not match a range starting 2026-07-25. Segment by
  local dates rather than by the UTC timestamps that appear in CSV exports.

## Layout

```
ghl/client.py     authenticated client: throttling, retries, pagination
ghl/segments.py   filter helpers, mailability guard, CSV export
cli.py            read-only command line interface
```

## Writes

No write path is implemented yet, deliberately. An untested POST against
`/emails/schedule` would reach a real audience of tens of thousands. Write
support should land behind a dry-run default and an explicit confirmation flag.
