"""Find who clicked a GoHighLevel email, so no registration intent is lost.

There is no click-reporting endpoint. `GET /emails/statistics` and every
variation of it 404s, and `/contacts/search` rejects `lastEmailClickedAt`,
`emailClicked`, and friends as invalid fields. Click data is only reachable
per contact, three hops deep:

    /conversations/search?contactId=      -> conversation id
    /conversations/{id}/messages          -> message, meta.email.messageIds
    /conversations/messages/email/{id}    -> {"status": "clicked"}

`status` is authoritative and takes `delivered` / `opened` / `clicked`.

Walking that for every recipient would be ~11,000 contacts and hours of calls,
so the candidate set is narrowed by tag first. The campaigns are configured to
apply "opened webinar invite" / "clicked webinar invite" on interaction, which
bumps the contact's dateUpdated. Sampling confirmed the shortcut is sound:
contacts carrying no open/click tag returned `delivered` for every message,
while tagged contacts returned the opens and clicks. Opens are included in the
candidate net as well as clicks -- a click cannot happen without the tracker
firing -- so a campaign that tags opens but not clicks is still covered.

Two traps this module exists to avoid:

**A click is per message, not per contact.** A contact who clicked a stock-pick
link in the newsletter and a contact who clicked "reserve my seat" in a webinar
invite both end up with `status: clicked`, and both look identical at the
contact level. Registering the first person into a webinar they never asked
about is a real cost. So clicks are attributed to the specific send, and only
sends that actually carried a registration link count as registration intent.

**Which sends carried one is detected, not assumed.** Each send's rendered HTML
is fetched and searched for the WebinarJam domain. Hardcoding a subject list
would silently mis-classify the moment a subject line is edited in the UI --
which is exactly what happened to this week's A3.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .client import GHLClient, GHLError

# Tags the campaigns apply on interaction. Membership plus a recent
# dateUpdated is what makes the per-contact walk affordable.
INTERACTION_TAGS = [
    "clicked webinar invite", "clicked email", "clicked newsletter",
    "clicked replay link", "clicked ticket link", "clicked recap vid",
    "opened webinar invite", "opened email", "opened newsletter",
    "opened pf invite", "clicked pf invite",
]

WEBINARJAM_HOST = "event.webinarjam.com"


@dataclass
class Send:
    id: str
    name: str
    subject: str
    scheduled: datetime
    recipients: int
    tracking: bool
    asks_registration: bool = False


@dataclass
class Clicker:
    contact_id: str
    email: str
    first: str
    last: str
    phone: str
    tags: list[str] = field(default_factory=list)
    # send name -> status, for this week's sends only
    events: dict[str, str] = field(default_factory=dict)

    @property
    def register_sends(self) -> list[str]:
        return sorted(s for s, st in self.events.items() if st == "clicked")


def _ms_to_dt(ms) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def recent_sends(client: GHLClient, days: int = 7) -> list[Send]:
    """Completed email sends from the last `days`, flagged for a register link.

    A send counts as asking for a registration if its rendered HTML contains the
    WebinarJam domain. That is checked rather than inferred from the subject,
    because subjects get edited in the UI after the template is built.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[Send] = []
    for row in client.email_schedules(limit=100):
        when = _ms_to_dt(row.get("dateScheduled"))
        if not when or when < cutoff:
            continue
        if row.get("status") not in ("complete", "sent"):
            continue
        send = Send(
            id=row.get("id", ""),
            name=row.get("name") or row.get("subject") or row.get("id", ""),
            subject=(row.get("subject") or "").strip(),
            scheduled=when,
            recipients=int(row.get("successCount") or 0),
            tracking=bool(row.get("hasTracking")),
        )
        url = row.get("nonTrackingDownloadUrl") or row.get("downloadUrl")
        if url:
            try:
                body = urllib.request.urlopen(url, timeout=45).read().decode("utf-8", "replace")
                send.asks_registration = WEBINARJAM_HOST in body
            except Exception:
                # Unreadable body: assume it asks, so a real click is never
                # dropped. A false positive here only widens the review list.
                send.asks_registration = True
        out.append(send)
    return sorted(out, key=lambda s: s.scheduled)


def candidates(client: GHLClient, since: str, until: str):
    """Contacts carrying an interaction tag and touched in the window."""
    seen: set[str] = set()
    for tag in INTERACTION_TAGS:
        filters = [
            {"field": "tags", "operator": "eq", "value": tag},
            {"field": "dateUpdated", "operator": "range",
             "value": {"gte": since, "lte": until}},
        ]
        try:
            for contact in client.search_contacts(filters):
                if contact["id"] not in seen:
                    seen.add(contact["id"])
                    yield contact
        except GHLError:
            continue


def contact_events(client: GHLClient, contact_id: str,
                   by_subject: dict[str, str]) -> dict[str, str]:
    """Per-send status for one contact, restricted to sends in `by_subject`.

    Only the strongest status per send is kept: a message can be reported
    `opened` on one row and `clicked` on another, and the click is the fact
    that matters.
    """
    rank = {"delivered": 0, "opened": 1, "clicked": 2}
    found: dict[str, str] = {}
    try:
        conv = client.request("GET", "/conversations/search",
                              params={"locationId": client.location_id,
                                      "contactId": contact_id})
    except GHLError:
        return found

    for cv in conv.get("conversations", []):
        try:
            payload = client.request("GET", f"/conversations/{cv['id']}/messages",
                                     params={"limit": 50})
        except GHLError:
            continue
        msgs = payload.get("messages", {})
        msgs = msgs.get("messages", msgs) if isinstance(msgs, dict) else msgs
        for m in msgs or []:
            if m.get("messageType") != "TYPE_EMAIL":
                continue
            meta = (m.get("meta") or {}).get("email") or {}
            send_name = by_subject.get((meta.get("subject") or "").strip())
            if not send_name:
                continue
            for eid in meta.get("messageIds") or []:
                try:
                    em = client.request("GET", f"/conversations/messages/email/{eid}",
                                        params={"locationId": client.location_id})
                except GHLError:
                    continue
                status = (em.get("emailMessage") or {}).get("status")
                if not status:
                    continue
                if rank.get(status, -1) > rank.get(found.get(send_name, ""), -1):
                    found[send_name] = status
    return found


def subject_map(sends: list[Send]) -> tuple[dict[str, str], set[str]]:
    """(subject -> label, labels that carried a register link).

    Two sends can share a subject -- this week's A3 was sent twice, twelve
    minutes apart, under two campaign names. A message only records the subject,
    so those are indistinguishable per contact and collapse into one label.
    `asks_registration` is OR'd across a collision: if either send carried a
    register link, a click on that subject is registration intent.
    """
    labels: dict[str, str] = {}
    asks: set[str] = set()
    for s in sends:
        if not s.subject:
            continue
        if s.subject in labels:
            base = labels[s.subject].split(" (")[0]
            labels[s.subject] = f"{base} (x2)"
        else:
            labels[s.subject] = s.name
        if s.asks_registration:
            asks.add(labels[s.subject])
    # A relabelled collision must carry its register flag over to the new label.
    for s in sends:
        if s.subject and s.asks_registration:
            asks.add(labels[s.subject])
    return labels, asks


def scan(client: GHLClient, sends: list[Send], since: str, until: str,
         progress=None) -> list[Clicker]:
    """Everyone with a click on any of `sends`, with the sends named."""
    by_subject, _ = subject_map(sends)
    results: list[Clicker] = []
    checked = 0
    for contact in candidates(client, since, until):
        checked += 1
        if progress and checked % 25 == 0:
            progress(checked, len(results))
        events = contact_events(client, contact["id"], by_subject)
        if not any(v == "clicked" for v in events.values()):
            continue
        results.append(Clicker(
            contact_id=contact["id"],
            email=(contact.get("email") or "").strip().lower(),
            first=contact.get("firstName") or "",
            last=contact.get("lastName") or "",
            phone=contact.get("phone") or "",
            tags=contact.get("tags") or [],
            events=events,
        ))
    if progress:
        progress(checked, len(results))
    return results


def split_by_intent(clickers: list[Clicker], sends: list[Send]
                    ) -> tuple[list[Clicker], list[Clicker]]:
    """(clicked a send carrying a register link, clicked only other sends)."""
    _, asks = subject_map(sends)
    intent, other = [], []
    for cl in clickers:
        (intent if any(s in asks for s in cl.register_sends) else other).append(cl)
    return intent, other
