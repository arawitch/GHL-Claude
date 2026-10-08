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

Commands that edit contacts say so and default to a dry run; everything else is
read-only. Nothing sends an email.

```bash
python3 cli.py info                       # account summary
python3 cli.py tags --search newsletter   # find tags
python3 cli.py workflows --status published
python3 cli.py schedules                  # existing email campaign schedules
python3 cli.py count  --tag "weekly newsletter subscriber" --mailable
python3 cli.py export --tag "weekly newsletter subscriber" --mailable \
                      --out lists/newsletter.csv

python3 cli.py sync-webinar --product everwebinar --list        # webinar ids
python3 cli.py sync-webinar --product everwebinar --webinar-id 7
python3 cli.py sync-webinar --product everwebinar --webinar-id 7 --apply
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

## Campaign audiences

Two builders, and the difference between them is the point.

| Module | Ranks by | Because the ask is |
| --- | --- | --- |
| `ghl/replaylead.py` | click behaviour, then opens | a click on a replay link |
| `ghl/chartlead.py` | **how recently they attended a webinar**, then clicks | attending a webinar |

Tier order should follow the action being requested. Ranking a replay chase by
attendance, or a webinar invite by clicks, puts the wrong people at the top.

### Attendance tags are the only real recency signal here

Engagement tags carry no timestamp, and `dateUpdated` is not a substitute: a
bulk send or a tagging run rewrites it across the whole list. On 2026-08-05 a
60-day and a 90-day window returned an identical **11,212** for that reason.

Attendance tags are dated *by name* -- `7/30 attended`, `attended 6-29`,
`3/12 attended` -- so they record when someone actually turned up, and no amount
of later sending overwrites it. `chartlead.py` groups them into recent / this
year / older, and puts undated tags (`everwebinar attended` and friends) in the
oldest tier rather than guessing them into a recent one.

### Exclusions follow the funnel, not a flat customer rule

The ladder is indicators → setup call → bots → Options Navigator, so anyone
holding *any* rung is excluded -- that is `OWNS_PITCHED_PRODUCT`. Front-end
buyers (`njc frontend buyer`, `purchased workshop`, `prop bootcamp member`, the
futures purchases) are kept deliberately: they have paid before and own no
indicator package, which makes them among the strongest names on the list. See
`smstarget.py` for the split and why `cancelled masters program` counts as a
former rather than current customer.

Built 2026-08-05 for the chart-makeover webinar:

| Tier | Count |
| --- | ---: |
| 1 attended recently + clicked | 25 |
| 2 attended recently | 26 |
| 3 attended this year + clicked | 126 |
| 4 attended this year | 81 |
| 5 attended, older or undated | 477 |
| 6 registered but never attended | 1,637 |
| **tiers 1-6, tagged `chart makeover invite`** | **2,372** |
| 7-8 email engagement, no webinar history | 9,395 |

Tiers 7-8 exist in the export but are not tagged. Given ~168k sends/month
against an 8% open rate, expanding into people with no webinar history at all
should be a deliberate decision rather than a default.

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

### Two products, two APIs, one key

`cli.py sync-webinar --product` picks between them:

| | `webinarjam` | `everwebinar` |
| --- | --- | --- |
| What | one-off live events | evergreen and just-in-time rooms |
| This account | id **2**, "Bot Webinar" | id **7**, "Bot Webinar" |
| Schedules | dated sessions with global ids | the literal string `Just in time` |
| Timezone set on it | `America/Los_Angeles` | **`America/New_York`** |

A `webinar_id` only means something inside its own product, so id 2 and id 7 are
unrelated despite sharing a name. A live id spans **every session ever scheduled
under it** — id 2 holds both the 9/24 and 10/1 events in one list of 198 — so
`--schedule-id` is needed to tag one event rather than both. `--list` prints the
ids, and omitting `--schedule-id` prints the schedules.

An evergreen room has no dated session, so the `has_run` / `--settle-minutes`
machinery is skipped for it: a just-in-time session is already over for whoever
registered. It gets one stable `everwebinar …` tag namespace rather than a
per-date prefix, which would mint new tags daily.

### There is no webhook

Several third-party guides describe a `POST /webhooks` endpoint taking a bearer
token. It does not exist. Probing with a deliberately wrong path settles it in
both directions — a fake route returns a 404 HTML page, while every real route
returns `{"errors":{"api_key":[...]}}`:

| Route | Exists |
| --- | --- |
| `POST /{product}/webinars`, `/webinar`, `/register` | yes |
| `POST /{product}/registrants` — **registrants *and* attendance** | yes |
| `POST /{product}/attendees` | no (404) |
| `POST /{product}/webhooks` | no (404) |
| `POST /{product}/zzznotreal` — control | no (404) |

So attendance is **polled, not pushed**, which is why this is a cron job rather
than a trigger. `/registrants` carries the same fields as the dashboard CSV:
`attended_live`, `time_live`, `attended_replay`, `time_replay`,
`purchased_live`, `revenue_live`.

### A regenerated key fails in a way that does not look like a key problem

An old key answers `401 {"api_key":"API access is not allowed!"}` — which reads
like a plan or permissions issue, not a stale credential. Regenerating the key
in WebinarJam invalidates every copy of it immediately. The environment's
`WEBINARJAM_API_KEY` was found revoked this way on 2026-10-08, meaning the sync
had been failing silently; `_post` now names the likely cause in the error.

`WJ_API_KEY` is accepted as an alias for the same variable.

### Running it on a schedule

`.github/workflows/webinar-sync.yml` runs hourly at :17. Secrets:

| Secret | What |
| --- | --- |
| `WEBINARJAM_API_KEY` (or `WJ_API_KEY`) | WebinarJam → My Webinars → Advanced Settings → API custom integration |
| `GHL_API_KEY` / `GHL_LOCATION_ID` | email sub-account; needs `contacts.write` |
| `GHL_SMS_API_KEY` / `GHL_SMS_LOCATION_ID` | SMS sub-account; omit to sync one side only |

Scheduled runs target the evergreen room and write. `workflow_dispatch` defaults
to a dry run and can target a live event by schedule id.

**A scheduled workflow only fires from the repository's default branch.** On a
non-default branch the cron never runs and `workflow_dispatch` shows no button,
which is indistinguishable from a workflow that runs and finds nothing.

### What the attendance tags do and do not mean

- **A zero-second view is not a view.** 4 of the 10 10/1 replay viewers logged
  `00:00:00` — they opened the room and left. Under `MIN_VIEW_SECONDS` (120) the
  role is not granted, because replay watchers convert at 6.5% against 1.4% for
  registrants who watched nothing, so a zero-second open in the replay cohort
  hands a no-show the warmest follow-up in the sequence.
- **Attendance is not written before the event.** Covered under the send plan:
  `attended_live` is `No` for everyone until the session runs.
- **Customers are skipped, which makes the tags an incomplete attendance
  record.** `skip_tags` defaults to `smstarget.OWNS_PITCHED_PRODUCT`, so anyone
  who already owns what the webinar sells is left untagged entirely. On the 10/1
  event that is the difference between 48 real attendees and 16 tagged ones.
  That is deliberate — it keeps owners out of sequences keyed on the tag — but
  it means `10/1 attended` answers "who attended and is still a prospect", not
  "who attended". `--include-customers` turns it off.

Verified against a month of hand-tagging: on the 10/1 live event the sync
independently reproduced the attendance split and flagged the one registrant
with no GHL contact record — a $3,800 bot customer carrying no ownership tag
anywhere, found by hand only via the order table.

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
