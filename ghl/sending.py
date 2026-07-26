"""Build defensible email send lists.

GHL's DND flag is not the whole suppression story for this location. Several
thousand contacts carry suppression *tags* -- "do not email", "spamtrap",
"complainer", "soft bounce" -- that the DND flag does not reflect. A segment
built only from `MAILABLE` will happily include all of them.

Everything here is read-only: these helpers produce filters and counts.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import MAILABLE, all_of, has_tag

# Tags that must never receive marketing email, discovered by auditing the
# location's 544 tags. Ordered roughly by how much damage a send would do.
SUPPRESSION_TAGS = [
    "spamtrap",        # sending here is the fastest route to a blocklist
    "complainer",      # previously hit "report spam"
    "never send",      # largest single suppression set in UOO
    "do not email",    # explicit opt-out, not reflected in the DND flag
    "soft bounce",
    "remove tag",
    "remove from bootcamp",
    "remove from follow up",
    "remove from workflow",
    "remove from 12/18 follow up",
    "do not push webinar",
]

# Tags GHL/campaigns set on positive interaction. Membership in any of these
# is the closest thing to an engagement signal the search API exposes -- there
# is no lastActivity, open, or click *field* to filter on.
ENGAGEMENT_TAGS = [
    "opened webinar invite", "opened pf invite", "opened email", "opened newsletter",
    "clicked webinar invite", "clicked pf invite", "clicked email", "clicked newsletter",
    "clicked replay link", "clicked recap vid", "clicked ticket link",
    "2/19 clicked invite", "clicked 1/16 invite", "clicked 2/12 invite",
    "clicked 3/12 invite", "1/16 clicked", "3/12 clicked wed",
    "engaged", "feb 5 engaged", "1/8 highly engaged", "12/18 highly engaged",
    "replied",
]


def not_tagged(tag: str) -> dict:
    return {"field": "tags", "operator": "not_eq", "value": tag}


def suppression_filters() -> list[dict]:
    return [not_tagged(t) for t in SUPPRESSION_TAGS]


def safe_send(*extra: dict) -> list[dict]:
    """Mailable, minus every suppression tag. The floor for any bulk send."""
    return all_of(*extra, MAILABLE, suppression_filters())


def engaged(*extra: dict) -> list[dict]:
    """safe_send() narrowed to contacts with at least one engagement tag."""
    any_engagement = {"group": "OR", "filters": [has_tag(t) for t in ENGAGEMENT_TAGS]}
    return safe_send(any_engagement, *extra)


def validated(*extra: dict) -> list[dict]:
    """safe_send() narrowed to addresses GHL has confirmed deliverable.

    validEmail is only populated once GHL has actually sent to an address, so
    this doubles as a "has send history" filter.

    Check validation_data_available() before using this: where GHL has not
    populated validEmail, this returns an empty list rather than a conservative
    one, which does not look like a failure.
    """
    return safe_send({"field": "validEmail", "operator": "eq", "value": True}, *extra)


def validation_data_available(client: GHLClient) -> bool:
    """Whether GHL has populated validEmail for this location at all.

    Two things filter on validEmail -- the `validated` send tier and
    reactivation's confirmed_bad cohort -- and both fail quietly when the field
    is empty. `validated` returns no contacts and confirmed_bad excludes no
    contacts, neither of which looks like an error: one reads as "no one
    qualified", the other as "nothing to exclude".

    Not hypothetical -- sub-account U23Jnu7rscfzAOUmSevW has no contact with
    validEmail == true at all, so both readings are wrong there. Checked at
    runtime rather than hardcoded, since whether GHL has populated the field is
    a property of the location the token happens to point at.
    """
    return client.count_contacts(
        all_of({"field": "validEmail", "operator": "eq", "value": True})) > 0


def audit(client: GHLClient) -> dict[str, int]:
    """Funnel from raw contact count down to a defensible send list."""
    return {
        "total": client.count_contacts(),
        "mailable": client.count_contacts(all_of(MAILABLE)),
        "safe_send": client.count_contacts(safe_send()),
        "engaged": client.count_contacts(engaged()),
        "validated": client.count_contacts(validated()),
    }


def suppression_breakdown(client: GHLClient) -> list[tuple[str, int]]:
    """Per-tag count of contacts a naive mailable segment would wrongly include."""
    rows = []
    for tag in SUPPRESSION_TAGS:
        rows.append((tag, client.count_contacts(all_of(has_tag(tag), MAILABLE))))
    return sorted(rows, key=lambda r: -r[1])
