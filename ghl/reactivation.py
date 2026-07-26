"""Split the suppressed population into what may be re-verified and what may not.

The distinction this module exists to enforce: a hard bounce is a fact about
the recipient's mailbox and does not change when you change sending domain,
but a *reputation* block is a fact about the sender and does. This location's
2023-2025 failure rates (62-100%) are a reputation signature, not a list-quality
one, so a large share of those failures were valid mailboxes refusing a poisoned
sender. Those are recoverable. Genuine bad addresses are not.

An opt-out is a third thing again, and the important one: consent withdrawal is
permanent and domain-independent. Those contacts must never reach a verification
service, because a verifier will happily return "valid" for an address you are
not permitted to mail, and that green tick is how they end up back in a send.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import EMAIL_DND_ON_STATUSES, all_of, has_tag
from .sending import not_tagged

# Every per-channel status that means "email DND is on", not just "active".
# See segments.EMAIL_DND_ON_STATUSES for why the list is shared and why the off
# case is expressed as not_eq rather than eq "inactive".
EMAIL_DND_ON = [{"field": "dndSettings.Email.status", "operator": "eq", "value": s}
                for s in EMAIL_DND_ON_STATUSES]
EMAIL_DND_OFF = [{"field": "dndSettings.Email.status", "operator": "not_eq", "value": s}
                 for s in EMAIL_DND_ON_STATUSES]
HAS_EMAIL = {"field": "email", "operator": "exists"}

# Consent withdrawn or reputation-toxic. Never upload, never mail, no exceptions.
NEVER_UPLOAD_TAGS = ["do not email", "complainer", "spamtrap"]

# Tags that mark a delivery failure rather than a withdrawal of consent.
FAILURE_TAGS = ["never send", "soft bounce"]


def never_upload() -> list[dict]:
    """Contacts that must not be sent to a verification service.

    Either an unsubscribe is recorded (global or email-channel DND) or they
    carry an explicit opt-out / abuse tag.
    """
    return [{"group": "OR", "filters": [
        *EMAIL_DND_ON,
        {"field": "dnd", "operator": "eq", "value": True},
        *[has_tag(t) for t in NEVER_UPLOAD_TAGS],
    ]}]


def verify_candidates() -> list[dict]:
    """Suppressed by a delivery failure, with no opt-out of any kind on record.

    These are the only contacts it is appropriate to re-verify: something went
    wrong with delivery, but nobody asked to stop hearing from you.
    """
    return all_of(
        HAS_EMAIL,
        {"group": "OR", "filters": [has_tag(t) for t in FAILURE_TAGS]},
        EMAIL_DND_OFF,
        {"field": "dnd", "operator": "eq", "value": False},
        [not_tagged(t) for t in NEVER_UPLOAD_TAGS],
    )


def confirmed_bad() -> list[dict]:
    """Verify candidates GHL has already recorded as undeliverable.

    Worth excluding from a paid verification run: you would be paying to be
    told what you already know.

    Only as good as validEmail, which is barely populated in this location --
    49 contacts carry it at all and none are true. So this cohort currently
    resolves to 3 contacts and removes almost nothing. Check
    sending.validation_data_available() before treating a small number here as
    "the list is already clean" rather than "GHL has no data to answer with".
    """
    return all_of(*verify_candidates(),
                  {"field": "validEmail", "operator": "eq", "value": False})


def worth_verifying() -> list[dict]:
    """verify_candidates() minus addresses already known bad.

    With validEmail unpopulated this is all but identical to
    verify_candidates(); the subtraction is a safeguard for when GHL does have
    delivery data, not an active filter today.
    """
    return all_of(*verify_candidates(),
                  {"field": "validEmail", "operator": "not_eq", "value": False})


def suppressed_addresses(client: GHLClient) -> set[str]:
    """Every lower-cased address belonging to a contact who opted out.

    Contacts are deduplicated by address here because this location contains
    duplicate records for the same person. When one record carries the opt-out
    and another does not, the clean duplicate passes verify_candidates() on its
    own merits -- and mailing it would still breach that person's opt-out. The
    address, not the contact id, is the unit consent attaches to.
    """
    return {
        (c.get("email") or "").strip().lower()
        for c in client.search_contacts(filters=never_upload())
        if c.get("email")
    }


def never_reached() -> list[dict]:
    """Contacts carrying no suppression and no engagement, and never delivered to.

    These were acquired during 2023-2025 and mailed into a domain that was being
    rejected at the gateway, so nothing arrived and no open was ever recorded.
    "Unengaged" here is an artefact of the outage, not a statement about the
    contact -- 97.8% have no delivery record of any kind.

    Deliverability is the only thing verification settles. It says nothing about
    whether someone still wants to hear from you after two years of silence, so
    this pool needs a slow re-engagement ramp rather than admission to the
    regular weekly send.
    """
    from .sending import ENGAGEMENT_TAGS, safe_send
    no_engagement = [not_tagged(t) for t in ENGAGEMENT_TAGS]
    return safe_send(*no_engagement)


def summary(client: GHLClient) -> dict[str, int]:
    return {
        "never_upload": client.count_contacts(never_upload()),
        "verify_candidates": client.count_contacts(verify_candidates()),
        "confirmed_bad": client.count_contacts(confirmed_bad()),
        "worth_verifying": client.count_contacts(worth_verifying()),
    }
