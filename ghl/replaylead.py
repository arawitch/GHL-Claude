"""Audience for a replay-chase campaign: people who engaged with a past webinar
invite but did not see the one just run.

Built from three kinds of tag, in descending order of what they prove:

  registered  -- signed up for a past webinar. The strongest signal available
                 in tag form: they gave a time commitment, not just a click.
  clicked     -- clicked an invite. Intent, one step short of signing up.
  opened      -- opened an invite. Weakest, but the largest pool by far.

**Invite tags are not all engagement tags.** `2/19 webinar invite` (26,231
contacts) and `feb 12 invite` (6,000) record that an invite was *sent*, not that
anyone did anything with it. Including them would more than double the list with
people who have never once responded, which is how a replay chase turns into a
complaint spike. Only the opened/clicked/registered forms are used here.

Excluded throughout: suppression tags, current customers (they own what the
webinar sells), and anyone who attended the event or has already watched its
replay -- chasing someone with a recording they have seen is the fastest way to
teach them to ignore you.

One thing this cannot do: filter by *when* the engagement happened. These tags
carry no timestamp, and `dateUpdated` is not a substitute -- a bulk send or a
tagging run rewrites it for the whole list. On 2026-08-05 a 60-day and a 90-day
window returned an identical 11,212 for that reason. Tier order is the closest
honest proxy: a past registrant is a better bet than an opener regardless of
date.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import MAILABLE
from .sending import SUPPRESSION_TAGS
from .smstarget import OWNS_PITCHED_PRODUCT

CLICKED_INVITE = [
    "clicked webinar invite", "clicked pf invite", "2/19 clicked invite",
    "clicked 1/16 invite", "clicked 2/12 invite", "clicked 3/12 invite",
    "3/12 invite click", "1/16 clicked", "3/12 clicked wed",
]

OPENED_INVITE = ["opened webinar invite", "opened pf invite"]

PAST_REGISTRANT = [
    "1/16 registrant", "1/8 registrant", "12/15 register", "12/18 register",
    "12/18 registrant", "2/12 register", "2/19 register", "3/12 register",
    "4/16 register", "4/2 register", "aml oh register", "everwebinar register",
    "feb 5 register", "fotc-ots registrant", "futures webinar register",
    "oct options web register", "oh register", "pf bootcamp register",
    "pf register re enroll", "webjam futures register",
]

# Sent-an-invite tags, deliberately unused. Named here so the next person does
# not "helpfully" add them back.
DELIVERY_ONLY = ["2/19 webinar invite", "feb 12 invite", "4/16 invite",
                 "day trading invite", "1/26 trade room invite"]


def _any(tags: list[str]) -> dict:
    return {"group": "OR", "filters": [
        {"field": "tags", "operator": "eq", "value": t} for t in tags]}


def base(event: str) -> list[dict]:
    """Mailable, not suppressed, not a customer, and did not see this event."""
    excluded = SUPPRESSION_TAGS + OWNS_PITCHED_PRODUCT + [
        f"{event} attended", f"{event} replay"]
    return list(MAILABLE) + [
        {"field": "tags", "operator": "not_eq", "value": t} for t in excluded]


def tiers(event: str) -> list[tuple[str, list[dict]]]:
    """Strongest signal first, so a truncated send still takes the best people."""
    root = base(event)
    return [
        ("1 registered for a past webinar", root + [_any(PAST_REGISTRANT)]),
        ("2 clicked an invite", root + [_any(CLICKED_INVITE)]),
        ("3 opened an invite", root + [_any(OPENED_INVITE)]),
    ]


def audience(event: str) -> list[dict]:
    """The whole pool in one filter, for counting or a single export."""
    return base(event) + [_any(PAST_REGISTRANT + CLICKED_INVITE + OPENED_INVITE)]


def counts(client: GHLClient, event: str) -> list[tuple[str, int]]:
    rows = [(label, client.count_contacts(f)) for label, f in tiers(event)]
    rows.append(("combined", client.count_contacts(audience(event))))
    return rows
