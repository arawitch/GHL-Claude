"""Sync WebinarJam attendance into GoHighLevel tags.

Replaces the manual loop of exporting a CSV after every webinar and tagging by
hand. Runs against both sub-accounts, because a contact's history is split
across them: engagement history sits in the email account, phone and DND truth
in the SMS account.

Two lessons from tagging these cohorts by hand are baked in:

  * Bot customers are judged on five validated ownership tags, never on
    "new bot user" (163 contacts, zero Options Bot orders, 121 of them
    fx customer -- the retired FX bot) and never on "new combo purchase".
  * Writes are skipped when the tag is already present. GHL's tag endpoint is
    idempotent, so a blind re-tag is harmless but costs a request per contact
    per run, and this runs hourly.
"""

from __future__ import annotations

from typing import Iterable

from .client import GHLClient, GHLError
from .webinarjam import WebinarJamClient, phone_of, state_of, watch_seconds

# Validated against paid order records: every tag here has a high share of
# members holding an Options Bot order. Excluded on the same evidence:
# "new bot user" and "new combo purchase".
BOT_OWNER_TAGS = frozenset({
    "options bot sale", "options bot presale", "options auto trader",
    "option and bot combo", "option bot combo",
})

# Ownership of the other product that disqualifies a bot invite. "flight path
# attended" and "flight path absent" are webinar attendance, not ownership --
# using them would cut 257 live prospects.
FLIGHT_PATH_TAGS = frozenset({"flight path member"})

# A registrant who opened the replay room and left inside this window saw none
# of the content and is tagged as a no-show, not a watcher.
MIN_WATCH_SECONDS = 120


def tags_for(state: str, prefix: str, row: dict) -> list[str]:
    """Tag names for one registrant.

    `prefix` namespaces the event: "everwebinar" for the always-on just-in-time
    room, or a date like "10/1" for a one-off live event, matching the
    convention already in the account.
    """
    if state in ("attended", "replay") and watch_seconds(row) < MIN_WATCH_SECONDS:
        state = "absent"
    return [f"{prefix} {state}"]


def _lookup(client: GHLClient, email: str, phone: str | None) -> list[dict]:
    """Find a contact by email, then by phone.

    Phone is a real fallback, not a formality: jonwc2@gmail.com registered under
    an address that has no contact record, and only the phone match surfaced the
    record carrying his bot-ownership tag.
    """
    hits = list(client.search_contacts(
        [{"field": "email", "operator": "eq", "value": email}], page_limit=20))
    if not hits and phone:
        hits = list(client.search_contacts(
            [{"field": "phone", "operator": "eq", "value": phone}], page_limit=20))
    return hits


def sync(wj: WebinarJamClient, webinar_id: int, prefix: str,
         accounts: Iterable[tuple[str, GHLClient]], *,
         skip_customers: bool = True, create_missing: bool = False,
         schedule_contains: str | None = None, dry_run: bool = True) -> dict:
    """Pull registrants and apply attendance tags. Returns a report.

    A live webinar_id spans every session ever scheduled under it -- id 2 holds
    both the 9/24 and 10/1 events in one list of 198 -- so `schedule_contains`
    narrows to a single date before anything is tagged. Without it, both events'
    registrants would land under one prefix.
    """
    rows = list(wj.registrants(webinar_id))
    if schedule_contains:
        needle = schedule_contains.lower()
        rows = [r for r in rows if needle in (r.get("schedule") or "").lower()]
    report = {"registrants": len(rows), "by_state": {}, "written": 0,
              "created": 0, "skipped_customer": 0, "not_found": 0,
              "already_tagged": 0, "failed": 0, "detail": []}

    # resolve every registrant in every account first, so ownership is judged on
    # the union of both before anything is written
    resolved: dict[str, dict] = {}
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        if not email:
            continue
        phone = phone_of(row)
        entry = resolved.setdefault(email, {"row": row, "phone": phone,
                                            "tags": set(), "ids": {}})
        for label, client in accounts:
            for c in _lookup(client, email, phone):
                entry["ids"].setdefault(label, []).append(c["id"])
                entry["tags"] |= {t.lower() for t in (c.get("tags") or [])}

    for email, entry in resolved.items():
        row = entry["row"]
        state = state_of(row)
        report["by_state"][state] = report["by_state"].get(state, 0) + 1
        wanted = tags_for(state, prefix, row)

        if skip_customers and (entry["tags"] & BOT_OWNER_TAGS
                               or entry["tags"] & FLIGHT_PATH_TAGS):
            report["skipped_customer"] += 1
            continue
        if not entry["ids"]:
            report["not_found"] += 1
            if not (create_missing and entry["phone"]):
                report["detail"].append(("not_found", email))
                continue

        for label, client in accounts:
            ids = entry["ids"].get(label) or []
            if not ids:
                if not create_missing:
                    continue
                payload = {"locationId": client.location_id, "email": email,
                           "firstName": (row.get("first_name") or "").strip(),
                           "lastName": (row.get("last_name") or "").strip(),
                           "tags": wanted, "source": f"WebinarJam {prefix}"}
                if entry["phone"]:
                    payload["phone"] = entry["phone"]
                if dry_run:
                    report["created"] += 1
                    continue
                try:
                    client.post("/contacts/", payload)
                    report["created"] += 1
                except GHLError as exc:
                    report["failed"] += 1
                    report["detail"].append(("create", email, str(exc)[:120]))
                continue

            missing = [t for t in wanted if t not in entry["tags"]]
            if not missing:
                report["already_tagged"] += 1
                continue
            for cid in ids:
                if dry_run:
                    report["written"] += 1
                    continue
                try:
                    client.post(f"/contacts/{cid}/tags", {"tags": missing})
                    report["written"] += 1
                except GHLError as exc:
                    report["failed"] += 1
                    report["detail"].append(("tag", email, str(exc)[:120]))
    return report
