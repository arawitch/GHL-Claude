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

## ⚠️ Before sending an email containing a one-click registration link

**Turn UTM tracking OFF on that send.**

GoHighLevel wraps links in its click tracker and appends its own UTM parameters.
On the 2026-07-26 newsletter that produced:

```
https://link.msgsndr.com/email-tracking/d87b88b75f5
  ?contactId={{contact.id}}&first_name={{contact.first_name}}
  &last_name={{contact.last_name}}&email={{contact.email}}
  &timezone=GMT-7&schedule_id=1
  &utm_source=email&utm_medium=email marketing      <-- unencoded space
```

A raw space is not valid in a URL. Most clients tolerate it; strict corporate
mail gateways may rewrite or reject the whole link. On that send, both
registrations that recorded a click but never reached WebinarJam were corporate
domains (`caduluth.com`, `otcservices.com`), while every consumer domain
succeeded. Not proof, but the pattern fits.

Checklist for any send carrying a one-click link:

1. **UTM tracking off** for that campaign
2. `schedule_id` matches the session number for that week (1, 2, 3 ...) -- this
   is the *session* number, not the global schedule id the API uses
3. Include a visible fallback beneath the one-click CTA:
   `Didn't work? https://event.webinarjam.com/gyywz/register/088v6bgy`
4. Send yourself a real test (not a preview) and click it, so merge fields
   resolve and the redirect is exercised end to end

After the send, find the clicks and recover anyone who did not reach WebinarJam:

```bash
python3 cli.py clicks --webinar-id 53 --schedule-id 107 --prefix "7/30" \
                      --out lists/clicks.csv
python3 cli.py register --webinar-id 53 --schedule-id 107 \
                        --file lists/clicks.csv --apply
python3 cli.py sync-webinar --webinar-id 53 --schedule-id 107 --apply
```

### Finding clicks is harder than it should be

There is **no click-reporting endpoint**. `GET /emails/statistics` and every
variation of it 404s, and `/contacts/search` rejects `lastEmailClickedAt`,
`emailClicked`, `lastEmailOpenedAt` and friends as invalid fields. Click data is
only reachable per contact, three hops deep:

```
/conversations/search?contactId=      -> conversation id
/conversations/{id}/messages          -> message, meta.email.messageIds
/conversations/messages/email/{id}    -> {"status": "clicked"}
```

`status` is authoritative: `delivered` / `opened` / `clicked`. Walking it for
every recipient would be ~11,000 contacts, so `cli.py clicks` narrows the
candidate set by tag first — the campaigns apply `opened/clicked webinar invite`
on interaction, which bumps `dateUpdated`. Sampling confirmed the shortcut:
contacts with no open/click tag returned `delivered` for every message.

Four traps the command exists to handle:

**A click is per message, not per contact.** Someone who clicked a stock-pick
link in the newsletter and someone who clicked "Reserve My Seat" look identical
at contact level. So clicks are attributed to a specific send, and only sends
carrying a register link count as registration intent. Which sends those are is
**detected, not assumed** — a hardcoded subject list breaks the moment a subject
is edited in the UI, which is what happened to A3 this week.

**Searching the HTML for `event.webinarjam.com` does not work.** GHL rewrites
every link in a tracked send to `link.msgsndr.com`, and `nonTrackingDownloadUrl`
returns a body **byte-identical** to the tracked one rather than a raw copy. The
2026-07-26 newsletter carried a one-click register link and scored "no register
link" — which would have dropped 23 clickers from review. Links are resolved one
hop through the tracker instead:

```
https://link.msgsndr.com/email-tracking/d87b88b75f5
  -> 302 https://event.webinarjam.com/gyywz/register/088v6bgy/1click
```

The tracker returns **403 to the default urllib User-Agent**, and that failure
reads as "no register link" rather than as an error, so a browser UA is sent.

**A click can be ambiguous even on a send that asks for registration.** If a
send has a register link *and* something else clickable, `status: clicked` does
not say which was clicked — there is no per-link data in the API. The 7/26
newsletter had both a register link and a Loom video, so its clickers land in a
third bucket rather than being guessed at. A send whose only links are the
one-click and its own fallback is *not* ambiguous: both go to WebinarJam, so any
click on it is registration intent.

#### Resolving the ambiguous bucket: ask for the per-link report

**The GHL UI has per-link click data that the API does not expose.** When the
command reports an ambiguous bucket, do not guess and do not bulk-register —
ask for the campaign's link-level click report, which lists name, address, click
count and timestamp per link. On 2026-07-29 that collapsed 17 ambiguous
newsletter clickers down to **one** genuine unregistered click. Registering all
17 would have put 16 people who watched a Loom video into a webinar.

That report is also better evidence than a single click flag, because it shows
repeat clicks — the signature of a link that is not working. Two of the twelve
newsletter register-link clickers clicked 3 and 7 times.

**Click tracking off means no click data.** Turning tracking off protects the
one-click link (see the UTM warning above) but makes clicks on that send
unrecordable. That is the right trade: an untracked link is also unrewritten, so
the one-click reaches WebinarJam directly. Absence of click data on an untracked
send is not absence of clicks — check WebinarJam registrations instead.

**`successCount` is unreliable on small sends.** The 23-recipient Track B send
on 2026-07-29 reported `successCount: 0, failed: 0, error: 0` while every
sampled recipient had actually received it. Verify small sends by looking for
the message on a contact, not by reading the counter.

## ⚠️ What actually drives clicks on this list

The first Week 1 draft clicked at **0.07–0.13%**. The seven highest-clicking
webinar invites in this location's send archive were pulled and read; they share
a structure the draft had none of. Anything written for Track A should follow it.

| | Their winners | The draft that failed |
| --- | --- | --- |
| Greeting | `Hey {{contact.first_name}},` | `Hi …` |
| The problem | an observable market condition — *"One headline comes out... SPY rips."* | a maxim — *"the market rewards discipline"* |
| Recognition | second-person fragments, one per line: *"You wait too long. / You enter too early. / You chase the move."* | none |
| The turn | *"Sound familiar?"* | none |
| The offer | a bulleted **"I'll walk you through:"** list | a paragraph |
| CTAs | **two** — an inline text link mid-body, then a P.S. with a second | one button |
| Subject | the time is in it: `Tomorrow at 2:`, `Will you be joining at 2?`, `Going live in 15 mins` | `The market rewards discipline` |

Two things worth knowing before copying the formula:

**The shortest emails click best.** `Will you be joining at 2?` and `Going live
in 15 mins` are four and five short paragraphs with a single plain text link,
and they outperform everything longer. Do not pad them.

**The winners contain no performance figures.** This corrects an earlier warning
here. The `5 trades. 5 wins.` and `$125 per contract` subject lines belong to
*daily recap* sends to a ~3,100 list — not to the webinar invites carrying the
11–23% campaign click rates. So the invite format can be copied wholesale
without importing the earnings-claim problem, and there is no trade-off to make.

Click rate is also downstream of open rate, which halved (20.6% → 11.15%) over
the same period. Subject lines carrying a time and a question are what recovered
it before. `previewText` on each template is now distinct from the subject
rather than a copy of it, so the inbox line is not wasted repeating itself.

## Deliverability: what is actually set up

Verified from DNS on 2026-08-05, after closers reported their mail landing in
spam from **both** GHL and Gmail, including emails with no links at all.

| | `universityofoptions.com` | `mg.universityofoptions.com` |
| --- | --- | --- |
| MX | Google Workspace | Mailgun |
| SPF | `include:_spf.google.com ~all` | `include:mailgun.org ~all` |
| DKIM | `google._domainkey`, 2048-bit | `mailo._domainkey`, **1024-bit** |
| DMARC | `p=quarantine`, reporting to mxtoolbox | inherits |
| Sends | closers, 1:1 | all marketing, `From: dan@mg.…` |

**Authentication is not the problem.** Both paths sign and align correctly, and
neither domain is listed on Spamhaus DBL or SURBL.

### Google Postmaster Tools, `universityofoptions.com`, 120 days to 2026-08-05

| Metric | Reading |
| --- | --- |
| Domain reputation | **High**, flat across the whole window |
| DKIM / SPF / DMARC | **100%** every day |
| User-reported spam | ~0%, with brief spikes to 0.5% (Apr 13) and 0.3% (early Aug) |
| IP reputation | ~50% Medium / 50% High Apr–Jun, **all High from July** |

**This refutes an earlier hypothesis recorded here.** Having seen two
independently authenticated paths both land in spam, the conclusion drawn was
that the organizational domain's reputation was impaired and dragging every
sender under it. Postmaster says otherwise: at Gmail this domain is in the best
reputation band available, with essentially no spam complaints. The load
argument below is still worth acting on for its own sake, but it is not
evidence of a reputation problem, and it does not explain the closers.

Two things follow, and both matter more than the original theory:

1. **Postmaster only reports Gmail.** A domain can read High at Gmail while
   Outlook, Yahoo or a corporate gateway filters it hard — and the corporate
   gateways are exactly where the one-click failures clustered
   (`caduluth.com`, `otcservices.com`, `fairwaymc.com`). Diagnosing the closers
   means finding out which providers the complaining recipients are on. Gmail
   has already been cleared.
2. **The data is sparse.** Every panel carries "Data shown with missing
   records", and the IP chart has gaps on most days, which is what Postmaster
   looks like below its ~100 messages/day reporting threshold. So this is a
   confident reading of a *thin* sample of the root domain's traffic.

The send-volume load, unchanged as an observation:

| Month | Sends | Delivered |
| --- | ---: | ---: |
| 2026-04 | 28 | 196,506 |
| 2026-06 | 23 | 165,617 |
| 2026-07 | 25 | 167,902 |

~168k/month while the open rate fell 20.6% → 11.15% → 7.67%. Since that volume
sends as `mg.`, its reputation lives on the **`mg.` Postmaster property**, which
has not yet been read. Do not attribute the open-rate collapse to placement
until it has been.

### ⚠️ Do not move the closers onto `mg.`

Three reasons, in order of how quickly they bite:

1. **`mg.` has no inbox.** Its MX points at Mailgun. A closer sending from
   `@mg.universityofoptions.com` has replies routed to Mailgun's inbound, not
   their Gmail. They lose replies silently.
2. `mg.` carries the complaint history of every bulk send. "Warmed" means it can
   carry volume, not that it is trusted for personal mail.
3. It inverts the point of the split, which is to keep bulk away from the domain
   humans converse from.

A closer domain has to be a **separately registered domain**, because reputation
inherits within an org domain. A new subdomain of `universityofoptions.com`
inherits the problem it is meant to escape.

### Cheap fixes worth doing regardless

- **The Mailgun DKIM key is 1024-bit.** The Google key on the root is 2048-bit.
  Google's sender guidelines call for 2048; Mailgun supports it and it is a
  dashboard toggle plus a DNS record swap.
- **Check whether Mailgun has this account on a shared IP pool.** At ~168k/month
  the volume is past the point where a dedicated IP is normally recommended. If
  the reputation problem is IP-level rather than domain-level, a new domain does
  not fix it — and that distinction is visible in Google Postmaster Tools, which
  reports IP and domain reputation separately.

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

| Slot | Track | Audience | Template | Sent by |
| --- | --- | --- | --- | --- |
| mon-invite-1 | B | engaged list, minus registrants | `W1-A1-Mon-NotReg` | GHL |
| tue-invite-2 | B | engaged list, minus registrants | `W1-A2-Tue-NotReg` | GHL |
| wed-invite-3 | B | engaged list, minus registrants | `W1-A3-Wed-NotReg` | GHL |
| wed-registered-primer | A | registrants | `W1-B1-WedAM-Registered` | GHL |
| *48h / 24h / 1h / 15min* | A | registrants | — | **WebinarJam** |
| thu-am-invite | B | engaged list, minus registrants | `W1-A4-Thu8am-NotReg` | GHL |
| thu-noon-invite | B | engaged list, minus registrants | `W1-A5-ThuNoon-NotReg` | GHL |
| thu-15min-invite | B | engaged list, minus registrants | `W1-A6-Thu145-NotReg` | GHL |
| thu-replay | post | no-shows | `W1-D1-ThuPM-NoShow` | GHL |
| fri-replay-final | post | no-shows | `W1-D2-Fri-NoShow` | GHL |
| fri-attendee-next | post | attendees | `W1-C1` / `W1-C2` | GHL |

Three of the six invites land on Thursday. That is not aggression for its own
sake — it is the shape of every above-average event in the archive. The Thursday
midday and 15-minute sends are the two shortest emails on the list and among the
best-clicking. `wed-registered-primer` goes to registrants but carries no join
link and no logistics, so it does not collide with WebinarJam's reminders.

GHL keeps exactly what WebinarJam does not do: persuading people who have not
registered, and everything after the event ends. Pass `--reminders ghl` to add
the registrant slots back, but only if WebinarJam's reminders are disabled or
landing in spam -- with both live, registrants receive two sets.

Track B wants persuasion rather than logistics and must have registrants removed
from every send, so it never collides with what WebinarJam is sending.

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

Pass the verifier's bad verdicts via `--exclude-file` until they are tagged in
GHL. No filter can see them before then.

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
| Contacts | 48,978 |
| Mailable (email present, both DND flags off) | 39,983 |
| Sendable (mailable, minus suppression tags) | 28,856 |
| Engaged (sendable, with an open or click) | 10,752 |
| Tags | 544 |
| Custom fields | 278 |
| Custom values | 36 |
| Workflows | 366 (342 draft, 24 published) |

**Every one of the 75 webinar-related workflows is in `draft`.** No reminder,
no-show follow-up, or replay automation is running. Measured across 16 past
events, the live show rate is 27.5% on 4,171 registrations, and 3,269 no-shows
were recovered at 22.2% by replay.

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
