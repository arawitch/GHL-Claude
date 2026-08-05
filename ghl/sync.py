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

import time
from dataclasses import dataclass, field

from .client import GHLClient, GHLError
from .segments import has_tag
from .webinarjam import WebinarJamClient, classify

# Role -> tag suffix. The prefix is per-event, e.g. "7/30 register".
SUFFIXES = {
    "register": "register",
    "attended": "attended",
    "absent": "absent",
    "replay": "replay",
    "purchased": "purchased",
    "stayed": "stayed",
}


@dataclass
class SyncReport:
    registrants: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    tags_applied: dict[str, int] = field(default_factory=dict)
    already_tagged: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Contacts deliberately not tagged because they hold a skip_tag.
    skipped: dict[str, int] = field(default_factory=dict)


def find_contacts_by_email(client: GHLClient, email: str) -> list[dict]:
    """Every contact record holding this address. Usually one, sometimes more."""
    filters = [{"field": "email", "operator": "eq", "value": email}]
    return list(client.search_contacts(filters=filters, page_limit=20, max_records=20))


def add_tags(client: GHLClient, contact_id: str, tags: list[str]) -> None:
    client.request("POST", f"/contacts/{contact_id}/tags", json={"tags": tags})


def _tag_in(ghl: GHLClient, email: str, wanted: list[str], apply: bool,
            report: SyncReport, label: str,
            skip_tags: set[str] | None = None) -> bool:
    """Tag every record holding this address in one location. True if matched.

    `skip_tags` are tags whose holders must not be tagged at all. This exists
    because the sync is idempotent by design and runs on a schedule, so any
    manual cleanup it does not know about is silently undone on the next run.
    Current customers were stripped from the 7/30 attendance tags by hand; four
    hours later the scheduled task would have put every one of them back.
    """
    try:
        contacts = find_contacts_by_email(ghl, email)
    except GHLError as exc:
        report.errors.append(f"[{label}] {email}: lookup failed - {exc}")
        return False
    if not contacts:
        return False

    for contact in contacts:
        existing = set(contact.get("tags") or [])
        if skip_tags and {t.lower() for t in existing} & skip_tags:
            report.skipped[label] = report.skipped.get(label, 0) + 1
            continue
        missing = [t for t in wanted if t not in existing]
        for tag in wanted:
            bucket = report.already_tagged if tag in existing else report.tags_applied
            key = tag if label == "main" else f"{tag} [{label}]"
            bucket[key] = bucket.get(key, 0) + 1
        if missing and apply:
            try:
                add_tags(ghl, contact["id"], missing)
            except GHLError as exc:
                report.errors.append(f"[{label}] {email}: tagging failed - {exc}")
    return True


def sync(wj: WebinarJamClient, ghl: GHLClient, webinar_id: int, schedule_id: int,
         prefix: str, stayed_minutes: int = 0, apply: bool = False,
         event_finished: bool = True, secondary: GHLClient | None = None,
         skip_tags: list[str] | None = None) -> SyncReport:
    """Pull one session's registrants and mirror them into GHL tags.

    With apply=False nothing is written -- the report shows exactly what would
    change, which is the only safe way to run this the first time against a
    production contact database.

    `secondary` is an optional second location (the SMS sub-account). Sub-accounts
    hold separate contact databases, so a registrant may exist in one, both, or
    neither. Nothing is created: a contact absent from a location is simply not
    tagged there, and `matched` counts anyone found in at least one location.
    """
    report = SyncReport()

    for row in wj.registrants(webinar_id, schedule_id):
        report.registrants += 1
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue

        roles = classify(row, stayed_minutes=stayed_minutes,
                         event_finished=event_finished)
        wanted = [f"{prefix} {SUFFIXES[r]}" for r in roles if r in SUFFIXES]

        skip = {t.lower() for t in (skip_tags or [])}
        hit = _tag_in(ghl, email, wanted, apply, report, "main", skip)
        if secondary is not None:
            hit = _tag_in(secondary, email, wanted, apply, report, "sms", skip) or hit
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
