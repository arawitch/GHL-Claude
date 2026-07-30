"""Pick a small, high-intent SMS list for a webinar that is about to start.

SMS is not a smaller version of email. A text costs money per send, arrives with
no subject line to filter it, and reaches a channel people guard. So this does
not rank the whole list -- it takes the few hundred contacts with the strongest
evidence of *present* interest and stops.

Ranking, strongest first:

  Tier 1  opened or clicked an email this week AND has attended a past webinar
          -- paying attention right now, and has a history of actually showing up
  Tier 2  clicked an email this week
  Tier 3  opened an email this week

Present attention is ranked above attendance history on purpose. For a message
sent hours before the event, what predicts acting in the next few hours is
whether they are reading the emails now, not whether they came in March. Past
attendance is the tie-breaker that lifts Tier 1 above Tier 2, not a tier of its
own.

--------------------------------------------------------------------------
The trap: DND does not sync between locations
--------------------------------------------------------------------------
The SMS sub-account is a separate contact database, and **its DND state is
independent of the main location's**. On 2026-07-30, 12 of a 300-contact list
that passed every DND and suppression check in the main location were
`dndSettings.SMS.status == "active"` in the SMS sub-account -- people who had
opted out of texts, invisible to any filter run against the main location alone.

So eligibility is checked *twice*: once in the main location, where the
engagement tags live, and again in the SMS location, where the send happens and
where the opt-out is recorded. A contact missing from the SMS location is
dropped too -- it cannot be messaged from there.

Non-US numbers are excluded. They are a consent and cost problem, and a 2 PM
Pacific webinar is a poor fit for them regardless.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import GHLClient, GHLError
from .sending import SUPPRESSION_TAGS

# Tags marking someone who has actually shown up to a past event. Registration
# tags are deliberately not here: registering is cheap, attending is the signal.
ATTENDED_TAGS = [
    "everwebinar attended", "webjam futures attended", "flight path attended",
    "attended futures", "oct options web attended", "12/15 attendee",
    "nov 6 attended", "1/8 attended", "12/18 attended", "open house attended",
    "3/12 attended", "10/10 attended", "8/29 attended", "feb 5 attended",
    "2/5 webinar attended", "ffs attended", "attended 4-10", "7/18 attended",
    "1/16 attendee", "12/11 attended", "options attended",
]

CLICK_TAGS = ["clicked webinar invite", "clicked email", "clicked newsletter"]
OPEN_TAGS = ["opened webinar invite", "opened email"]

# Current customers and members. The webinar pitches the programs these people
# have already bought, so an invite is at best wasted and at worst irritating.
BUYER_TAGS = [
    "uoo member", "options member", "customer", "fx customer",
    "purchased", "purchased workshop", "flight path member",
    "foundingmembermarketmentor", "gold member", "current masters member",
    "fs member", "prop bootcamp member", "grandfathered - active subscription",
    "njc frontend buyer", "njc workshop purchase", "options nav new purchase",
    "options nav 4k new purchase", "options navigator purchased",
    "new options purchase", "new combo purchase", "futures new purchase",
    "futures 4k new purchase", "options bot sale", "options bot presale",
    "june oh purchase", "oh purchase",
    "masters gold 3 month upgrade trial (free options trading course)",
]

# Deliberately NOT in BUYER_TAGS, each for a reason:
#   cancelled masters program   -- a *former* customer, so not a current one.
#                                  These are win-back targets and among the
#                                  warmest non-members on the list.
#   weekly newsletter subscriber-- free; a subscriber is not a buyer.
#   njc- clicked purchase link  -- clicked the link, did not buy.

# BUYER_TAGS answers "should this person get an invite?". A different question
# is "should this person get the post-webinar sales follow-up?", and it splits
# the buyers in two. Someone who already owns Options Navigator or the bot is
# being sold what they have. Someone who bought a low-ticket front-end product
# is the *best* audience for that pitch, not the worst.
#
# So only the first group is stripped from the attendance tags. The split was
# set by Audry on 2026-07-30: the bot presale counts as owning the product,
# while prop bootcamp is a separate offer and stays a live upsell target.
OWNS_PITCHED_PRODUCT = [
    "uoo member", "options member", "customer", "fx customer",
    "flight path member", "grandfathered - active subscription",
    "current masters member", "gold member", "fs member",
    "options bot presale", "options bot sale",
    "options nav new purchase", "options nav 4k new purchase",
    "options navigator purchased",
]

# Buyers who stay in the follow-up: they bought something else, or something
# smaller, and are the natural upsell.
FRONT_END_BUYER = [
    "prop bootcamp member", "njc frontend buyer", "njc workshop purchase",
    "purchased workshop", "new combo purchase", "futures new purchase",
    "futures 4k new purchase", "june oh purchase", "oh purchase",
    "masters gold 3 month upgrade trial (free options trading course)",
    "cancelled masters program",
]


@dataclass
class Target:
    contact_id: str
    sms_contact_id: str
    phone: str
    first: str
    last: str
    email: str
    tier: str


def _any_tag(tags: list[str]) -> dict:
    return {"group": "OR", "filters": [
        {"field": "tags", "operator": "eq", "value": t} for t in tags]}


def eligible(event_tag: str) -> list[dict]:
    """Reachable by SMS, not registered, not a customer -- per the main location."""
    return [
        {"field": "phone", "operator": "exists"},
        {"field": "dnd", "operator": "eq", "value": False},
        {"field": "dndSettings.SMS.status", "operator": "not_eq", "value": "active"},
        {"field": "tags", "operator": "not_eq", "value": event_tag},
    ] + [{"field": "tags", "operator": "not_eq", "value": t}
         for t in SUPPRESSION_TAGS + BUYER_TAGS]


def disqualified(contact: dict, event_tag: str) -> str | None:
    """Why this contact should not receive the invite, checked against one record.

    Used to re-screen an already-tagged list. The registration tag is the moving
    part: someone can register in the minutes between selection and sending, and
    the copy tells them to sign up for something they are already signed up for.
    """
    tags = {t.lower() for t in (contact.get("tags") or [])}
    if event_tag.lower() in tags:
        return "registered"
    hit = tags & {t.lower() for t in BUYER_TAGS}
    if hit:
        return f"customer ({sorted(hit)[0]})"
    hit = tags & {t.lower() for t in SUPPRESSION_TAGS}
    if hit:
        return f"suppressed ({sorted(hit)[0]})"
    if sms_blocked(contact):
        return "sms dnd"
    return None


def remove_tag(client: GHLClient, contact_id: str, tag: str) -> None:
    client.request("DELETE", f"/contacts/{contact_id}/tags", json={"tags": [tag]})


def sms_blocked(contact: dict) -> bool:
    """SMS opt-out as recorded in whichever location this contact came from."""
    if contact.get("dnd"):
        return True
    settings = (contact.get("dndSettings") or {}).get("SMS") or {}
    return settings.get("status") == "active"


def build(main: GHLClient, sms: GHLClient, event_tag: str, since: str, until: str,
          want: int = 300, progress=None) -> tuple[list[Target], dict[str, int]]:
    """Ranked, twice-checked SMS targets, best first.

    Returns (targets, rejection counts). Candidates are pulled in tier order and
    verified against the SMS location one at a time, stopping as soon as `want`
    have passed -- verifying the whole pool would be thousands of calls to
    discard most of them.
    """
    window = {"field": "dateUpdated", "operator": "range",
              "value": {"gte": since, "lte": until}}
    base = eligible(event_tag)
    tiers = [
        ("1 attention + attended before",
         base + [window, _any_tag(OPEN_TAGS + CLICK_TAGS), _any_tag(ATTENDED_TAGS)]),
        ("2 clicked this week", base + [window, _any_tag(CLICK_TAGS)]),
        ("3 opened this week", base + [window, _any_tag(OPEN_TAGS)]),
    ]
    sort = [{"field": "dateAdded", "direction": "desc"}]

    out: list[Target] = []
    seen: set[str] = set()
    rejected = {"duplicate": 0, "non_us": 0, "not_in_sms_location": 0, "sms_dnd": 0}

    for label, filters in tiers:
        if len(out) >= want:
            break
        for contact in main.search_contacts(filters, sort=sort):
            if len(out) >= want:
                break
            if contact["id"] in seen:
                rejected["duplicate"] += 1
                continue
            seen.add(contact["id"])
            phone = (contact.get("phone") or "").strip()
            if not phone.startswith("+1"):
                rejected["non_us"] += 1
                continue

            match = _find_in_sms(sms, contact.get("email"), phone)
            if not match:
                rejected["not_in_sms_location"] += 1
                continue
            if sms_blocked(match):
                # Opted out of texts in the location that sends them. Invisible
                # to every filter above, which only sees the main location.
                rejected["sms_dnd"] += 1
                continue

            out.append(Target(
                contact_id=contact["id"], sms_contact_id=match["id"], phone=phone,
                first=contact.get("firstName") or "", last=contact.get("lastName") or "",
                email=(contact.get("email") or "").strip().lower(), tier=label,
            ))
            if progress and len(out) % 25 == 0:
                progress(len(out), want)
    return out, rejected


def apply_tag(main: GHLClient, sms: GHLClient, targets: list[Target], tag: str,
              progress=None) -> dict[str, int]:
    """Tag the selected targets in both locations.

    The SMS location is where the workflow runs, so that tag is the one that
    matters; the main-location copy exists so the same people can be excluded
    from, or reported on alongside, the email sends. Both ids are already known
    from selection, so this is a straight write with no re-lookup -- and no risk
    of tagging a different contact than the one that was verified.
    """
    counts = {"sms": 0, "main": 0, "failed": 0}
    for i, t in enumerate(targets, 1):
        for label, client, contact_id in (("sms", sms, t.sms_contact_id),
                                          ("main", main, t.contact_id)):
            if not contact_id:
                continue
            try:
                client.request("POST", f"/contacts/{contact_id}/tags",
                               json={"tags": [tag]})
                counts[label] += 1
            except GHLError:
                counts["failed"] += 1
        if progress and i % 25 == 0:
            progress(i, len(targets))
    return counts


def rescreen(main: GHLClient, sms: GHLClient, tag: str, event_tag: str,
             apply: bool) -> tuple[int, dict[str, int]]:
    """Drop anyone from an already-tagged list who no longer qualifies.

    Screening happens against the SMS location, because that is where the
    registration tag is written by the WebinarJam sync and where an SMS opt-out
    is recorded. The tag is pulled from *both* locations when it goes, so the
    two do not drift.

    Returns (how many still hold the tag, reasons for removal).
    """
    holders = list(sms.search_contacts([{"field": "tags", "operator": "eq", "value": tag}]))
    reasons: dict[str, int] = {}
    removed = 0
    for contact in holders:
        why = disqualified(contact, event_tag)
        if not why:
            continue
        key = why.split(" (")[0]
        reasons[key] = reasons.get(key, 0) + 1
        removed += 1
        if not apply:
            continue
        try:
            remove_tag(sms, contact["id"], tag)
        except GHLError:
            pass
        email = (contact.get("email") or "").strip()
        if email:
            for twin in main.search_contacts(
                    [{"field": "email", "operator": "eq", "value": email}], max_records=5):
                try:
                    remove_tag(main, twin["id"], tag)
                except GHLError:
                    pass
    return len(holders) - removed, reasons


def top_up(main: GHLClient, sms: GHLClient, tag: str, event_tag: str,
           since: str, until: str, want: int, have: int,
           progress=None) -> tuple[list[Target], dict[str, int]]:
    """Select replacements, skipping anyone who already carries the tag."""
    if have >= want:
        return [], {}
    already = {(c.get("email") or "").strip().lower()
               for c in sms.search_contacts(
                   [{"field": "tags", "operator": "eq", "value": tag}])}
    picked, rejected = build(main, sms, event_tag, since, until,
                             want=want - have + len(already), progress=progress)
    fresh = [t for t in picked if t.email not in already][:want - have]
    return fresh, rejected


def _find_in_sms(sms: GHLClient, email: str | None, phone: str) -> dict | None:
    for field, value in (("email", (email or "").strip()), ("phone", phone)):
        if not value:
            continue
        try:
            hit = next(iter(sms.search_contacts(
                [{"field": field, "operator": "eq", "value": value}], max_records=1)), None)
        except GHLError:
            continue
        if hit:
            return hit
    return None
