"""Sync WebinarJam registrant data into GoHighLevel tags.

Webhooks are the right mechanism for instant reaction, but they fail silently:
a paused workflow or a dropped request looks exactly like "nobody attended".
This location has already been burned by that -- one past event recorded 26,231
invitations and zero attendance tags, and nobody noticed for weeks.

This sync is the repair path. It is idempotent, so running it twice is harmless,
and it reconciles what WebinarJam recorded against what GoHighLevel holds, which
turns a silent gap into a visible number.

Contacts are matched by email address. Duplicate contact records for the same
person are all tagged, because a segment built later will match on whichever
record it finds first.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .client import GHLClient, GHLError
from .segments import has_tag
from .webinarjam import WebinarJamClient, classify, phone_of

# Role -> tag suffix. The prefix is per-event, e.g. "7/30 register".
SUFFIXES = {
    "register": "register",
    "attended": "attended",
    "absent": "absent",
    "replay": "replay",
    "purchased": "purchased",
    "stayed": "stayed",
    # Not a webinar behaviour: "this person is still a prospect for what the
    # webinar sells". See PROSPECT_ROLE below.
    "prospect": "prospect",
}

# What someone did at the event, as opposed to who they are. Exactly these are
# re-asserted on every run, and any of them the current data does not support is
# removed.
#
# Needed because an evergreen room reuses one tag namespace across every
# session. marka797@gmail.com registered again on 10/7, attended nothing, and
# still carried "everwebinar attended" and "everwebinar replay" from an earlier
# session -- so the tags said he both attended and did not. Tags that only ever
# accumulate cannot describe a room that runs continuously.
#
# Only ever scoped to the prefix being synced: another event's tags are that
# event's record and are never touched.
STATE_ROLES = ("attended", "absent", "replay")

# Granted to everyone who does NOT already own what the webinar sells.
#
# This used to work the other way round: holders of an ownership tag were
# skipped entirely and got no tags at all. That protected a manual cleanup --
# customers were stripped from the 7/30 attendance tags by hand, and a blind
# re-run would have put them all back -- but it also meant attendance went
# unrecorded. jmacfarlane@hotmail.com watched 38 minutes of the evergreen
# webinar, the longest of anyone, and ended up tagged nothing at all because he
# holds "uoo member".
#
# So the two jobs are now separate. The attendance tags record what happened,
# for everybody. This one carries the marketing decision, and a send built on
# "<prefix> prospect" excludes owners structurally rather than by remembering to.
PROSPECT_ROLE = "prospect"


@dataclass
class SyncReport:
    registrants: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    tags_applied: dict[str, int] = field(default_factory=dict)
    already_tagged: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Contacts recorded but withheld the prospect tag, because they already own
    # what the webinar sells.
    skipped: dict[str, int] = field(default_factory=dict)
    # Stale state tags removed because the current data contradicts them.
    tags_removed: dict[str, int] = field(default_factory=dict)
    # Registrants with no contact record, and what was done about it.
    created: int = 0
    # Found only because a create collided with an existing record.
    matched_by_duplicate: int = 0


def find_contacts_by_email(client: GHLClient, email: str) -> list[dict]:
    """Every contact record holding this address. Usually one, sometimes more."""
    filters = [{"field": "email", "operator": "eq", "value": email}]
    return list(client.search_contacts(filters=filters, page_limit=20, max_records=20))


def find_contacts(client: GHLClient, email: str, phone: str | None) -> list[dict]:
    """Email first, then phone. The phone fallback is not a formality.

    Three evergreen registrants looked absent from GHL on an email-only lookup
    and all three were there: dartkat@gmail.com is "KD Wagner" on a record whose
    primary address is something else, emaxumov@gmail.com is "Nerye Maksumov",
    and jmacfarlane@hotmail.com sits under a secondary address in the SMS
    account. Creating them would have duplicated three live contacts -- GHL
    refused, which is how this was found.
    """
    hits = find_contacts_by_email(client, email)
    if hits or not phone:
        return hits
    return list(client.search_contacts(
        filters=[{"field": "phone", "operator": "eq", "value": phone}],
        page_limit=20, max_records=20))


# GHL rejects a duplicate create with the id of the record it collided with.
# That is more useful than the error: the registrant exists under another
# address or number, and the right move is to tag that record rather than
# report a miss.
DUPLICATE_MESSAGE = "does not allow duplicated contacts"


def _duplicate_contact_id(exc: GHLError) -> str | None:
    """Pull meta.contactId out of a duplicate-create rejection."""
    text = str(exc)
    if DUPLICATE_MESSAGE not in text:
        return None
    m = re.search(r'"contactId"\s*:\s*"([^"]+)"', text)
    return m.group(1) if m else None


def add_tags(client: GHLClient, contact_id: str, tags: list[str]) -> None:
    client.request("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})


def remove_tags(client: GHLClient, contact_id: str, tags: list[str]) -> None:
    client.request("DELETE", f"/contacts/{contact_id}/tags", json={"tags": tags})


def create_contact(client: GHLClient, email: str, row: dict,
                   tags: list[str], prefix: str) -> str | None:
    """Create a contact for a registrant who has none. Returns its id.

    Needed because the evergreen room draws registrations from outside GHL:
    of 8 registrants, 3 had no contact record, and two of those had watched
    29:55 and 14:30. Engaged viewers who exist only in WebinarJam cannot be
    followed up at all.

    A contact is only created with a dialable phone or none at all -- the
    registration form accepts free text, so phone_of() returns None for survey
    answers and bare hyphens rather than writing junk into the CRM.
    """
    payload = {
        "locationId": client.location_id,
        "email": email,
        "firstName": (row.get("first_name") or "").strip(),
        "lastName": (row.get("last_name") or "").strip(),
        "tags": tags,
        "source": f"WebinarJam {prefix}",
    }
    phone = phone_of(row)
    if phone:
        payload["phone"] = phone
    body = client.request("POST", "/contacts/", json=payload)
    return (body.get("contact") or {}).get("id")


def _tag_in(ghl: GHLClient, email: str, wanted: list[str], apply: bool,
            report: SyncReport, label: str,
            owner_tags: set[str] | None = None,
            prospect_tag: str | None = None,
            stale_tags: list[str] | None = None,
            row: dict | None = None, prefix: str = "",
            create_missing: bool = False) -> bool:
    """Reconcile every record holding this address in one location.

    Three things happen per record, in order:

      1. the attendance tags in `wanted` are asserted -- for everyone, owner or
         not, because they record what happened;
      2. `prospect_tag` is granted only if the record holds none of
         `owner_tags`, which is where the marketing decision lives;
      3. any tag in `stale_tags` is removed, because the current data
         contradicts it. Scoped to this event's prefix only.

    Returns True if a record was found or created.
    """
    try:
        contacts = find_contacts(ghl, email, phone_of(row) if row else None)
    except GHLError as exc:
        report.errors.append(f"[{label}] {email}: lookup failed - {exc}")
        return False

    if not contacts:
        if not (create_missing and row is not None):
            return False
        tags = list(wanted) + ([prospect_tag] if prospect_tag else [])
        if not apply:
            report.created += 1
            for tag in tags:
                key = tag if label == "main" else f"{tag} [{label}]"
                report.tags_applied[key] = report.tags_applied.get(key, 0) + 1
            return True
        try:
            create_contact(ghl, email, row, tags, prefix)
            report.created += 1
            for tag in tags:
                key = tag if label == "main" else f"{tag} [{label}]"
                report.tags_applied[key] = report.tags_applied.get(key, 0) + 1
            return True
        except GHLError as exc:
            # The duplicate rejection names the record it collided with, which
            # means the registrant does exist -- under another address or on a
            # number this lookup did not reach. Tag that record instead of
            # reporting a miss and losing them.
            cid = _duplicate_contact_id(exc)
            if cid:
                try:
                    add_tags(ghl, cid, tags)
                    for tag in tags:
                        key = tag if label == "main" else f"{tag} [{label}]"
                        report.tags_applied[key] = report.tags_applied.get(key, 0) + 1
                    report.matched_by_duplicate += 1
                    return True
                except GHLError as inner:
                    report.errors.append(f"[{label}] {email}: tagging the "
                                         f"duplicate {cid} failed - {inner}")
                    return False
            report.errors.append(f"[{label}] {email}: create failed - {exc}")
            return False

    for contact in contacts:
        existing = set(contact.get("tags") or [])
        lower = {t.lower() for t in existing}
        this = list(wanted)
        if prospect_tag:
            if owner_tags and lower & owner_tags:
                report.skipped[label] = report.skipped.get(label, 0) + 1
            else:
                this.append(prospect_tag)

        for tag in this:
            bucket = report.already_tagged if tag in existing else report.tags_applied
            key = tag if label == "main" else f"{tag} [{label}]"
            bucket[key] = bucket.get(key, 0) + 1
        missing = [t for t in this if t not in existing]
        if missing and apply:
            try:
                add_tags(ghl, contact["id"], missing)
            except GHLError as exc:
                report.errors.append(f"[{label}] {email}: tagging failed - {exc}")

        drop = [t for t in (stale_tags or []) if t in existing]
        for tag in drop:
            key = tag if label == "main" else f"{tag} [{label}]"
            report.tags_removed[key] = report.tags_removed.get(key, 0) + 1
        if drop and apply:
            try:
                remove_tags(ghl, contact["id"], drop)
            except GHLError as exc:
                report.errors.append(f"[{label}] {email}: untagging failed - {exc}")
    return True


def mirror_tag(source: GHLClient, target: GHLClient, tag: str, apply: bool,
               new_name: str | None = None) -> dict[str, int]:
    """Copy a tag's membership from one location into another.

    Sub-accounts hold separate contact databases, so a tag applied in one is
    invisible in the other. Matching is by email first and phone second: contact
    ids are per-location and never line up, and the same person can hold more
    than one record in either location, so every match is tagged rather than
    just the first.

    Nothing is created. A contact with no record in the target is reported, not
    invented -- inventing one would put a contact into SMS campaigns that has
    never been through the target location's consent flow.
    """
    counts = {"source": 0, "tagged": 0, "already": 0, "no_match": 0, "failed": 0}
    want = new_name or tag
    for contact in source.search_contacts(
            [{"field": "tags", "operator": "eq", "value": tag}]):
        counts["source"] += 1
        email = (contact.get("email") or "").strip()
        phone = (contact.get("phone") or "").strip()
        matches: list[dict] = []
        for field, value in (("email", email), ("phone", phone)):
            if not value:
                continue
            try:
                matches = list(target.search_contacts(
                    [{"field": field, "operator": "eq", "value": value}],
                    page_limit=20, max_records=20))
            except GHLError:
                matches = []
            if matches:
                break
        if not matches:
            counts["no_match"] += 1
            continue
        for row in matches:
            if want in (row.get("tags") or []):
                counts["already"] += 1
                continue
            if not apply:
                counts["tagged"] += 1
                continue
            try:
                add_tags(target, row["id"], [want])
                counts["tagged"] += 1
            except GHLError:
                counts["failed"] += 1
    return counts


def sync(wj: WebinarJamClient, ghl: GHLClient, webinar_id: int,
         schedule_id: int | None,
         prefix: str, stayed_minutes: int = 0, apply: bool = False,
         event_finished: bool = True, secondary: GHLClient | None = None,
         schedule_contains: str | None = None,
         skip_tags: list[str] | None = None,
         create_missing: bool = False) -> SyncReport:
    """Pull one session's registrants and mirror them into GHL tags.

    With apply=False nothing is written -- the report shows exactly what would
    change, which is the only safe way to run this the first time against a
    production contact database.

    `secondary` is an optional second location (the SMS sub-account). Sub-accounts
    hold separate contact databases, so a registrant may exist in one, both, or
    neither, and `matched` counts anyone found in at least one.

    `skip_tags` no longer suppresses tagging. Attendance is recorded for
    everyone; holders of those tags are withheld the `<prefix> prospect` tag
    instead, which is what a send should be built on.

    `create_missing` makes a contact for a registrant who has none, so the
    evergreen room's own traffic lands somewhere followable.
    """
    report = SyncReport()
    owner_tags = {t.lower() for t in (skip_tags or [])}

    for row in wj.registrants(webinar_id, schedule_id,
                              schedule_contains=schedule_contains):
        report.registrants += 1
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue

        roles = classify(row, stayed_minutes=stayed_minutes,
                         event_finished=event_finished)
        wanted = [f"{prefix} {SUFFIXES[r]}" for r in roles
                  if r in SUFFIXES and r != PROSPECT_ROLE]
        prospect_tag = f"{prefix} {SUFFIXES[PROSPECT_ROLE]}"

        # Any state this run did not assert is contradicted by the current data
        # and comes off. Only within this prefix, and only once the event has
        # run -- before that classify() returns no state at all, so clearing on
        # that basis would wipe a previous session's record for no reason.
        stale = []
        if event_finished:
            stale = [f"{prefix} {SUFFIXES[r]}" for r in STATE_ROLES
                     if r not in roles]

        common = dict(apply=apply, report=report, owner_tags=owner_tags,
                      prospect_tag=prospect_tag, stale_tags=stale, row=row,
                      prefix=prefix, create_missing=create_missing)
        hit = _tag_in(ghl, email, wanted, label="main", **common)
        if secondary is not None:
            hit = _tag_in(secondary, email, wanted, label="sms", **common) or hit
        if hit:
            report.matched += 1
        else:
            report.unmatched.append(email)

    return report


def reconcile(ghl: GHLClient, prefix: str, report: SyncReport,
              settle_seconds: float = 15.0) -> list[tuple[str, int, int]]:
    """Compare WebinarJam's counts against what GHL actually holds.

    A shortfall here is the signal that a webhook silently dropped events.

    GoHighLevel's tag counts are eventually consistent: a count taken straight
    after writing reports the pre-write value, so reconciling immediately
    reports a shortfall on every run and trains you to ignore it. Any apparent
    shortfall is therefore re-checked once after a settling delay, and only a
    gap that survives the recheck is reported.
    """
    rows = []
    pending = []
    for suffix in SUFFIXES.values():
        tag = f"{prefix} {suffix}"
        expected = report.tags_applied.get(tag, 0) + report.already_tagged.get(tag, 0)
        if not expected:
            continue
        try:
            actual = ghl.count_contacts([has_tag(tag)])
        except GHLError:
            actual = -1
        (pending if 0 <= actual < expected else rows).append((tag, expected, actual))

    if pending:
        time.sleep(settle_seconds)
        for tag, expected, _ in pending:
            try:
                actual = ghl.count_contacts([has_tag(tag)])
            except GHLError:
                actual = -1
            rows.append((tag, expected, actual))
    return rows
