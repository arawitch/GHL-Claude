"""Audience for a webinar, ranked by how recently someone actually attended one.

The funnel is webinar -> indicators purchase -> setup call -> bots and Options
Navigator. That decides the exclusions, and it is not the same as a plain "not a
customer" rule.

**Excluded:** anyone already holding what this funnel sells at *any* stage --
the indicators, the bots, Options Navigator, UOO membership. Selling someone the
entry point to a ladder they are already on wastes the send and reads as
carelessness. `OWNS_PITCHED_PRODUCT` already carries exactly that list.

**Kept on purpose:** front-end buyers -- `njc frontend buyer`, `purchased
workshop`, `prop bootcamp member`, the futures purchases. They have paid before,
which makes them likelier to pay again, and none owns an indicator package.

--------------------------------------------------------------------------
Recency comes from the tag names, not from dateUpdated
--------------------------------------------------------------------------
Engagement tags carry no timestamp, and `dateUpdated` is not a substitute: a
bulk send or a tagging run rewrites it across the whole list, which is why a
60-day and a 90-day window returned an identical 11,212 on 2026-08-05.

Attendance tags are different. They are *dated by name* -- `7/30 attended`,
`attended 6-29`, `3/12 attended` -- so they encode when the person actually
turned up, and that survives any amount of later bulk sending. Grouping them by
date is the only real recency signal in this account, so the tiers are built
from it directly.

Undated attendance tags (`everwebinar attended`, `webjam futures attended` and
friends) cannot be placed in time, so they sit in the oldest attendance tier
rather than being guessed into a recent one.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import MAILABLE
from .sending import SUPPRESSION_TAGS
from .smstarget import OWNS_PITCHED_PRODUCT
from .replaylead import CLICKED_INVITE, OPENED_INVITE, PAST_REGISTRANT

# Attended within roughly the last quarter, newest first.
ATTENDED_RECENT = ["7/30 attended", "7/18 attended", "attended 6-29"]

# Attended earlier the same year.
ATTENDED_THIS_YEAR = [
    "april 17 attended", "attended 4-10", "4/2 attended", "3/12 attended",
    "2/12 attended", "2/5 webinar attended", "feb 5 attended",
    "1/16 attendee", "1/8 attended",
]

# Last year, plus every attendance tag whose name carries no date at all.
ATTENDED_OLDER = [
    "12/18 attended", "12/15 attendee", "12/11 attended", "nov 6 attended",
    "oct options web attended", "oct options web joined", "10/10 attended",
    "8/29 attended",
    "everwebinar attended", "webjam futures attended", "attended futures",
    "open house attended", "ffs attended", "attended day trading",
    "options attended", "joined bootcamp", "flight path attended",
]

ALL_ATTENDED = ATTENDED_RECENT + ATTENDED_THIS_YEAR + ATTENDED_OLDER


def _any(tags: list[str]) -> dict:
    return {"group": "OR", "filters": [
        {"field": "tags", "operator": "eq", "value": t} for t in tags]}


def base(exclude_tags: list[str] | None = None) -> list[dict]:
    """Mailable, not suppressed, and not already on the product ladder."""
    excluded = SUPPRESSION_TAGS + OWNS_PITCHED_PRODUCT + list(exclude_tags or [])
    return list(MAILABLE) + [
        {"field": "tags", "operator": "not_eq", "value": t} for t in excluded]


def tiers(exclude_tags: list[str] | None = None) -> list[tuple[str, list[dict]]]:
    """Strongest first. Attendance outranks clicking because the ask is attendance.

    For the replay chase the order was inverted -- there the ask was a click, so
    click behaviour led. Tier order should follow the action being requested.
    """
    root = base(exclude_tags)
    return [
        ("1 attended recently + clicked", root + [_any(ATTENDED_RECENT), _any(CLICKED_INVITE)]),
        ("2 attended recently", root + [_any(ATTENDED_RECENT)]),
        ("3 attended this year + clicked", root + [_any(ATTENDED_THIS_YEAR), _any(CLICKED_INVITE)]),
        ("4 attended this year", root + [_any(ATTENDED_THIS_YEAR)]),
        ("5 attended, older or undated", root + [_any(ATTENDED_OLDER)]),
        ("6 registered but never attended", root + [_any(PAST_REGISTRANT)]),
        ("7 clicked an invite", root + [_any(CLICKED_INVITE)]),
        ("8 opened an invite", root + [_any(OPENED_INVITE)]),
    ]


# Tiers 1-6 are everyone with a demonstrated relationship to a webinar --
# attended one, or at least committed time by registering. Tiers 7-8 are email
# engagement with no webinar history, which is a far larger and much colder
# population. Given ~168k sends/month against an 8% open rate, expanding into
# them should be a deliberate decision rather than a default.
PRIORITY_TIERS = 6


def build(client: GHLClient, exclude_tags: list[str] | None = None,
          limit: int | None = None, progress=None) -> list[tuple[str, dict]]:
    """Deduplicated contacts in tier order, best first."""
    seen: set[str] = set()
    out: list[tuple[str, dict]] = []
    for label, filters in tiers(exclude_tags):
        added = 0
        for contact in client.search_contacts(
                filters, sort=[{"field": "dateAdded", "direction": "desc"}]):
            if limit is not None and len(out) >= limit:
                break
            if contact["id"] in seen:
                continue
            seen.add(contact["id"])
            out.append((label, contact))
            added += 1
        if progress:
            progress(label, added, len(out))
        if limit is not None and len(out) >= limit:
            break
    return out
