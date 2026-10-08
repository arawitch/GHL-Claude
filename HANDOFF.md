# Handoff — University Of Options GoHighLevel work

Context for a new session. Everything below is verified against the live API,
not assumed. Read `README.md` too — it documents the client's design and the
API gotchas in more detail.

## Account

| | |
| --- | --- |
| Location | University Of Options — `IyorbIIbJLsMLaqy8j1P` |
| Timezone | America/Los_Angeles |
| Contacts | 48,978 |
| Tags | 553 |
| Custom fields | 278 |
| Custom values | 36 |
| Workflows | 366 — **342 draft, 24 published** |

## Environment variables

| Variable | Status |
| --- | --- |
| `GHL_API_KEY` | set — private integration token, `pit-` prefix |
| `GHL_LOCATION_ID` | set |
| `WEBINARJAM_API_KEY` | **expected — the reason this session was started** |
| `GHL_SMS_API_KEY` / `GHL_SMS_LOCATION_ID` | pending, for the SMS sub-account |

Network allowlist already covers `services.leadconnectorhq.com`,
`webinarjam.com`, `support.webinarjam.com`. Note `support.webinarjam.com`
blocks the WebFetch user agent — fetch it with `curl -A "Mozilla/5.0 ..."`.

## What has been done

**List hygiene.** Two suppression leaks were found and closed. GHL's global
`dnd` flag misses per-channel email DND (`dndSettings.Email.status == "active"`)
— 3,700 contacts were email-suppressed without the global flag. Separately,
11,127 contacts carry suppression *tags* no DND field reflects, the largest
being `never send` (7,426) and `do not email` (7,421).

**Verification.** 21,099 addresses went through ZeroBounce in two batches.
Batch 1 (previously bounced) returned 89.6% valid; batch 2 (never successfully
delivered to) returned 95.7%. **20,010 addresses recovered.** 1,089 came back
invalid/abuse/spamtrap and are tagged `verified bad`.

The high valid rate confirmed the diagnosis: 2023–2025 failure rates of 62–100%
were a *sender reputation* problem, not a list-quality one. Those addresses were
valid mailboxes refusing a poisoned domain. A new domain was warmed in early
2026 and the failure rate is now ~0.3%.

**Tagging for a volume ramp.** Current send audience is `current email list`
at 11,102. Batches are pre-tagged so weekly sends just add one more tag:

| Tag | Contacts | Cumulative |
| --- | ---: | ---: |
| `current email list` | 11,102 | 11,102 |
| `email batch 1` | 2,772 | 13,874 |
| `email batch 2` | 3,468 | 17,342 |
| `email batch 3` | 4,334 | 21,676 |
| `email batch 4` | 5,414 | 27,090 |
| `email batch 5` | 1,263 | 28,353 |

Hold the ramp if bounces exceed 2%, complaints exceed 0.1%, or unsubscribes
double. Baseline is 0.3% failures.

**Tag cleanup.** 6,636 junk tags were deleted. They were created by importing a
CSV whose `tags` column held pipe-joined values, which GHL read as single tag
names. The export column is now `tags_REFERENCE_DO_NOT_IMPORT` with ` / `
separators so the importer cannot auto-map it. **CSVs exported before that fix
still carry the old header and will recreate the problem if re-imported.**

## Webinar funnel

Weekly live webinar, Thursday 2pm PT, hosted on WebinarJam.

Measured across 16 past events: 4,171 registrations, 1,238 attended live,
3,269 no-shows, 726 replay views. **Show rate 27.5%, replay recovery 22.2%.**

**Every one of the 75 webinar-related workflows is in `draft`.** No reminder,
no-show follow-up, or replay automation is running. Events that did have
purpose-built promo workflows (12/18, feb 5) showed 38% show rates against
12.4% for one that did not — suggestive, not proven.

Tag hygiene is inconsistent: `2/19` recorded 26,231 invited and **zero**
attendance tags, so per-event numbers are unreliable even though the trend is
clear. Automating this is the main open task.

## Audience

Acquisition is ~64% options-ebook opt-ins, 13% Facebook. **94% of the engaged
audience has never attended a webinar** and 97% have never purchased. Phone
coverage is high — 94% of engaged, 95% of past attendees, 97% of replay viewers.

This matters for copy: the audience is webinar-*unfamiliar* rather than
webinar-fatigued, and content assuming prior trading experience ("which trap
have you fallen into?") has to be reframed anticipatorily ("which would get you
first?").

## Open work

**1. `cli.py sync-webinar` — the main build.**

WebinarJam API, verified from their docs:

```
POST https://api.webinarjam.com/webinarjam/registrants
  api_key*      string(64)
  webinar_id*   integer
  schedule_id   int
  attended_live int 0-4   (0 all, 1 attended, 2 not, 3 left before ts, 4 left after ts)
  attended_replay int 0-4 (same pattern)
  purchased     int 0-2
  page          int
  attended_live_timestamp   int seconds
  attended_replay_timestamp int seconds
  date_range    int 0-8   (0 all time, 5 last 7 days, ...)
```

Base endpoint `https://api.webinarjam.com/webinarjam`, key is account-wide, from
Webinars dashboard → Advanced → API custom integration. Rate limit 20 calls/sec.

Response fields worth having: `email`, `first_name`, `last_name`, `phone`,
`phone_country_code`, `attended_live`, `time_live` (**watch duration**),
`entered_live`, `attended_replay`, `time_replay`, `purchased_live`,
`revenue_live`, `purchased_replay`, `revenue_replay`, **`twilio_consented_at`**,
`utm_source`, `utm_medium`, `utm_campaign`.

`time_live` gives a "heard the whole pitch" segment that does not currently
exist. `twilio_consented_at` is the compliant basis for the SMS sub-account.

Caveat from the docs: one `schedule_id` can cover an entire series, so
individual sessions are pinpointed with `date_range`. That matters for a weekly
recurring webinar and is the detail most likely to need checking against real
data.

The sync should be idempotent and able to backfill, so a missed webhook is
repairable — that is what would have caught the `2/19` gap.

**2. One webhook for instant registrant tagging.** GHL's Inbound Webhook is a
premium trigger at $0.01/execution after 100 free. Use it only for `register`,
so Track B excludes registrants in real time; let the API sync handle everything
else. GHL's Add Tag action cannot build tag names dynamically, so either use
static tags plus a date custom field, or accept weekly workflow edits. Date
custom fields **are** filterable — `customFields.{fieldId}` with a `range`
operator works; `eq` does not.

**3. Windows scheduled task** to refresh weekly send lists, since Track B
exports are snapshots that go stale as people register mid-week.

**4. SMS sub-account.** Sync only high-intent segments — attended, stayed past
the pitch, replay, purchased — not all registrants. Needs its own PIT.

**5. Thursday's webinar.** Deck is `UOO_Programs_Slides.pptx`, 52 slides, two
programs (Options Navigator ~$6,401–7,800, Auto Traders ~$2,800–5,800).
Outstanding: slide 41 shows four prices with two contradicting each other, and
slide 19's headline and body prices disagree. Slides 21–22 project trading
profits covering PayPal financing payments, which alongside 90–95% win-rate
claims warrants qualified review before going to cold contacts.

Five emails are drafted (3 invites, 2 replay) positioned as a decision-making
framework rather than another strategy — no earnings claims, which suits cold
traffic and sidesteps the compliance question entirely.

## Things that will waste time if rediscovered

- Workflows are **read-only** in the GHL API. `POST /workflows/` returns 404.
- Smart lists live at `/contacts/views`, which is **OAuth-only** and rejects
  private integration tokens. Tag the members instead to make them readable.
- Contact search pagination uses the `searchAfter` cursor; offset paging
  silently truncates.
- Date filters run in the location's timezone while `dateAdded` returns UTC, so
  a contact stamped `2026-07-25T06:03Z` will not match a range starting
  `2026-07-25`.
- Slow searches return `401 {"message":"Command timed out"}` — transient, not an
  auth failure. The client retries it.
- There are duplicate contact records for the same person. Deduplicate by
  email address, not contact id — consent attaches to the address.
