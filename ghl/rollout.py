"""Staged volume ramp for adding recovered contacts back into the send list.

Verification settled deliverability for 20,010 contacts, but not whether people
who have heard nothing since 2024 still want to hear from you. That second
question is answered by complaint rate, and complaint rate -- not bounce rate --
is what damages a domain that has already been rebuilt once.

So the recovered pool is added in steps rather than at once. Each step holds the
proven core constant and adds a bounded slice of new contacts, newest first on
the theory that the more recently someone opted in, the more likely they are to
recognise the sender and the less likely to report spam.

Nothing here sends. It produces the recipient list for one step.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import all_of, has_tag
from .sending import ENGAGEMENT_TAGS, engaged, not_tagged, safe_send

# Multiplier applied at each step. 1.25 keeps every increase inside the
# "no more than a modest jump" convention warming guidance assumes; raising it
# shortens the ramp and raises the risk that one bad step is unrecoverable.
DEFAULT_GROWTH = 1.25


def schedule(start: int, total: int, growth: float = DEFAULT_GROWTH) -> list[int]:
    """Volumes for each step, from the current proven volume up to the full pool."""
    steps, v = [start], start
    while v < total:
        v = min(int(v * growth), total)
        steps.append(v)
    return steps


def core() -> list[dict]:
    """The proven audience: safe, and with engagement history."""
    return engaged()


def recovered() -> list[dict]:
    """Safe contacts with no engagement tag -- the never-reached pool.

    After the suppression tags are cleared, batch-1 contacts land here too.
    """
    return safe_send(*[not_tagged(t) for t in ENGAGEMENT_TAGS])


def step_list(client: GHLClient, volume: int, exclude: set[str] | None = None):
    """Yield contacts for a step: the whole core, then recovered newest-first.

    Stops once `volume` contacts have been yielded. Addresses in `exclude` are
    skipped -- pass the verifier's bad verdicts here until they are tagged in
    GHL, since no filter can see them before then.
    """
    exclude = exclude or set()
    seen: set[str] = set()
    n = 0
    for filters in (core(), recovered()):
        sort = [{"field": "dateAdded", "direction": "desc"}]
        for contact in client.search_contacts(filters=filters, sort=sort):
            if n >= volume:
                return
            email = (contact.get("email") or "").strip().lower()
            if not email or email in exclude or email in seen:
                continue
            seen.add(email)
            n += 1
            yield contact
