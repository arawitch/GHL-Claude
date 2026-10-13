"""Register people who replied YES to a webinar invite text.

The SMS invite offers two paths: tap the link, or reply YES and we do it for
them. The second converts better -- 27.1% of past buyers have replied to a text
against 5.6% of never-buyers -- but it only works if the promise is kept within
hours, and at 3,900 recipients that cannot be manual.

Detection is deliberately NOT done here. GHL's workflow builder can trigger on
an inbound message containing "YES" and add a tag the instant it arrives, which
is faster and more reliable than any polling this could do, and workflows cannot
be created through the public API anyway. So the division is:

    GHL workflow   inbound SMS matches YES  ->  add REPLY_TAG        (instant)
    this module    REPLY_TAG and not DONE_TAG -> register, add DONE_TAG

A delayed run therefore loses nothing: the tag is already on the contact and the
registration happens whenever this next runs.

Registering is idempotent in effect, not in the API: WebinarJam will happily
create a second registration for the same address, so DONE_TAG is what stops a
double send of its confirmation email.
"""

from __future__ import annotations

from .client import GHLClient, GHLError
from .webinarjam import WebinarJamClient, WebinarJamError

REPLY_TAG = "sms replied yes"
DONE_TAG = "sms yes registered"
FAILED_TAG = "sms yes register failed"


def pending(client: GHLClient, reply_tag: str = REPLY_TAG,
            done_tag: str = DONE_TAG) -> list[dict]:
    """Contacts who said YES and have not been registered yet."""
    return list(client.search_contacts(filters=[
        {"field": "tags", "operator": "eq", "value": reply_tag},
        {"field": "tags", "operator": "not_eq", "value": done_tag},
        {"field": "tags", "operator": "not_eq", "value": FAILED_TAG},
    ], page_limit=100))


def already_registered(wj: WebinarJamClient, webinar_id: int,
                       schedule_id: int | None) -> set[str]:
    """Addresses WebinarJam already holds for this session.

    Checked before registering rather than trusting DONE_TAG alone, because a
    contact can register themselves through the link after replying YES, and a
    second registration means a second set of WebinarJam reminder emails.
    """
    out = set()
    for row in wj.registrants(webinar_id, schedule_id):
        e = (row.get("email") or "").strip().lower()
        if e:
            out.add(e)
    return out


def run(client: GHLClient, wj: WebinarJamClient, webinar_id: int,
        schedule_id: int, *, reply_tag: str = REPLY_TAG,
        done_tag: str = DONE_TAG, apply: bool = False) -> dict:
    """Register every pending YES. Returns a report."""
    rep = {"pending": 0, "registered": 0, "already": 0, "no_email": 0,
            "failed": 0, "detail": []}
    people = pending(client, reply_tag, done_tag)
    rep["pending"] = len(people)
    if not people:
        return rep

    have = already_registered(wj, webinar_id, schedule_id)

    for c in people:
        email = (c.get("email") or "").strip().lower()
        if not email:
            rep["no_email"] += 1
            rep["detail"].append(("no email", c["id"]))
            continue

        if email in have:
            rep["already"] += 1
            if apply:
                try:
                    client.post(f"/contacts/{c['id']}/tags", {"tags": [done_tag]})
                except GHLError as exc:
                    rep["detail"].append(("tag", email, str(exc)[:120]))
            continue

        if not apply:
            rep["registered"] += 1
            continue

        try:
            wj.register(webinar_id, schedule_id, email,
                        first_name=(c.get("firstName") or "there").strip() or "there",
                        last_name=(c.get("lastName") or "").strip() or None,
                        phone=(c.get("phone") or "").strip() or None)
        except WebinarJamError as exc:
            rep["failed"] += 1
            rep["detail"].append(("register", email, str(exc)[:160]))
            # tag the failure so the next run does not retry it forever and
            # so a human can see who needs doing by hand
            try:
                client.post(f"/contacts/{c['id']}/tags", {"tags": [FAILED_TAG]})
            except GHLError:
                pass
            continue

        rep["registered"] += 1
        try:
            client.post(f"/contacts/{c['id']}/tags", {"tags": [done_tag]})
        except GHLError as exc:
            # Registered but not tagged: the next run would register them
            # again, which is why this is reported rather than swallowed.
            rep["detail"].append(("REGISTERED BUT NOT TAGGED", email, str(exc)[:120]))
    return rep
