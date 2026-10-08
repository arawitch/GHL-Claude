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

Three traps this module exists to avoid:

**A click is per message, not per contact.** A contact who clicked a stock-pick
link in the newsletter and a contact who clicked "reserve my seat" in a webinar
invite both end up with `status: clicked`, and both look identical at the
contact level. Registering the first person into a webinar they never asked
about is a real cost. So clicks are attributed to the specific send, and only
sends that actually carried a registration link count as registration intent.

**Which sends carried one is detected, not assumed.** Hardcoding a subject list
would silently mis-classify the moment a subject is edited in the UI, which is
what happened to this week's A3. But searching the HTML for the WebinarJam host
does not work either: GHL rewrites every link in a tracked send to its own click
tracker, and `nonTrackingDownloadUrl` returns a body byte-identical to the
tracked one rather than a raw copy. So the 2026-07-26 newsletter -- which
carried a one-click register link -- scored "no register link", which would have
dropped 23 clickers from review. Links are resolved one hop through the tracker
instead. (The tracker 403s the default urllib User-Agent, and that failure also
reads as "no register link", so a browser UA is sent.)

**A click can be ambiguous even on a send that asks for registration.** If a
send has a register link *and* something else clickable, `status: clicked` does
not say which was clicked -- the API exposes no per-link data. That newsletter
had both a register link and a Loom video, so its clickers cannot be treated as
registration intent. `split_by_intent` keeps them in a third bucket rather than
guessing. A send whose only links are the one-click and its own fallback is *not*
ambiguous: both go to WebinarJam.

To resolve that bucket, ask for the campaign's **link-level click report from the
GHL UI** -- it exists there even though the API does not expose it, and it lists
address, click count and timestamp per link. On 2026-07-29 it collapsed 17
ambiguous newsletter clickers to one genuine unregistered click; bulk-registering
the bucket would have put 16 video-watchers into a webinar.
"""

from __future__ import annotations

import re
import urllib.error
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

# GoHighLevel rewrites every link in a tracked send to its own click tracker, so
# the destination host is absent from the HTML. Both downloadUrl and
# nonTrackingDownloadUrl return the *same* rewritten body -- the "non-tracking"
# copy is byte-identical, not a raw one. Searching the HTML for the WebinarJam
# host therefore returns a false negative on any tracked send: the 2026-07-26
# newsletter carried a one-click register link and was scored "no register
# link", which would have dropped 23 clickers from review.
#
# The tracker resolves without merge fields, so each wrapped link is followed
# one hop to recover its destination.
TRACKER_RE = re.compile(r"https://link\.msgsndr\.com/email-tracking/[A-Za-z0-9]+")

# The default urllib User-Agent is rejected with a 403 by both the tracker and
# the storage host, which reads as "no register link" rather than as an error.
UA = {"User-Agent": "Mozilla/5.0 (compatible; GHL-Claude)"}


def _fetch(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


@dataclass
class Send:
    id: str
    name: str
    subject: str
    scheduled: datetime
    recipients: int
    tracking: bool
    asks_registration: bool = False
    # True when the send has a clickable destination that is NOT registration,
    # so a recorded click cannot be attributed to the register link. A send whose
    # only links are the one-click and its fallback is not ambiguous: both go to
    # WebinarJam, so any click on it is registration intent.
    ambiguous_click: bool = False


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

    A send asks for registration if any of its links resolves to WebinarJam, and
    a click on it is ambiguous if any link resolves anywhere else. Both are
    measured from the resolved destinations rather than inferred from the
    subject, which gets edited in the UI after the template is built.
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
                body = _fetch(url)
                dests = link_destinations(body)
                send.asks_registration = any(WEBINARJAM_HOST in d for d in dests)
                send.ambiguous_click = any(WEBINARJAM_HOST not in d for d in dests)
            except Exception:
                # Unreadable body: assume it asks and that a click is ambiguous,
                # so a real click is never silently dropped or auto-actioned.
                send.asks_registration = True
                send.ambiguous_click = True
        out.append(send)
    return sorted(out, key=lambda s: s.scheduled)


def link_destinations(body: str) -> set[str]:
    """Real destinations of a send's clickable links, tracker hops resolved.

    Unsubscribe and font links are not click targets and are excluded, so a send
    whose only real link is the register link is not scored ambiguous.
    """
    dests: set[str] = set()
    for raw in set(re.findall(r'href="([^"]+)"', body)):
        href = raw.replace("&amp;", "&")
        if "unsubscribe" in href or "fonts.googleapis.com" in href:
            continue
        m = TRACKER_RE.match(href)
        if not m:
            if href.startswith("http"):
                dests.add(href.split("?")[0])
            continue
        try:
            req = urllib.request.Request(m.group(0), headers=UA)
            resp = urllib.request.build_opener(_NoRedirect()).open(req, timeout=30)
            target = resp.headers.get("Location") or ""
        except urllib.error.HTTPError as exc:
            target = exc.headers.get("Location") or ""
        except Exception:
            target = ""
        dests.add((target or m.group(0)).split("?")[0])
    return dests


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The tracker's 302 target is the answer; following it wastes a request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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


def subject_map(sends: list[Send]) -> tuple[dict[str, str], set[str], set[str]]:
    """(subject -> label, labels asking for registration, labels that are ambiguous).

    Two sends can share a subject -- this week's A3 was sent twice, twelve
    minutes apart, under two campaign names. A message only records the subject,
    so those are indistinguishable per contact and collapse into one label. Both
    flags are OR'd across a collision: if either send carried a register link a
    click is intent, and if either was ambiguous the merged label is ambiguous.
    """
    labels: dict[str, str] = {}
    for s in sends:
        if not s.subject:
            continue
        if s.subject in labels:
            base = labels[s.subject].split(" (")[0]
            labels[s.subject] = f"{base} (x2)"
        else:
            labels[s.subject] = s.name
    # Second pass, so a label renamed by a collision still collects both flags.
    asks: set[str] = set()
    ambiguous: set[str] = set()
    for s in sends:
        if not s.subject:
            continue
        if s.asks_registration:
            asks.add(labels[s.subject])
        if s.ambiguous_click:
            ambiguous.add(labels[s.subject])
    return labels, asks, ambiguous


def scan(client: GHLClient, sends: list[Send], since: str, until: str,
         progress=None) -> list[Clicker]:
    """Everyone with a click on any of `sends`, with the sends named."""
    by_subject, _, _ = subject_map(sends)
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
                    ) -> tuple[list[Clicker], list[Clicker], list[Clicker]]:
    """(definite registration intent, ambiguous, no register link clicked).

    Definite means a click on a send whose every clickable link went to
    WebinarJam registration -- there is nothing else it could have been. Those
    are safe to auto-register. Ambiguous means the only register-carrying send
    they clicked also had something else clickable, so the click may have been
    for that instead; the API exposes no per-link data, so this cannot be
    resolved and is left for a human.
    """
    _, asks, ambiguous = subject_map(sends)
    definite: list[Clicker] = []
    unclear: list[Clicker] = []
    other: list[Clicker] = []
    for cl in clickers:
        clicked = set(cl.register_sends)
        if clicked & (asks - ambiguous):
            definite.append(cl)
        elif clicked & asks:
            unclear.append(cl)
        else:
            other.append(cl)
    return definite, unclear, other
