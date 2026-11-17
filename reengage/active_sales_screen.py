"""Screen out leads a rep is actively working, before enrolling them in an AI bot.

Edward Shoup (2026-11-16) was enrolled in the qualifier and the AI drop-off
follow-up while Joel was mid-close on a $4,800 sale. Nothing in the enrolment
path looked at the conversation, so the bot texted over the top of it.

`is_rep_working_them()` is that missing check. Call it per contact, live,
immediately before adding the trigger tag, and skip the contact when it
returns a reason.

A contact is skipped when ANY of these holds:
  * a tag that means a call is booked or confirmed
    (`has upcoming call`, `appt confirmed`)
  * a two-way SMS exchange in the last ACTIVE_DAYS days: the contact sent at
    least one message AND someone sent at least one back. A one-sided drip
    does not count, which is the whole point - those are the people the bot
    is for.

Both checks are live reads, never the CSV, because the CSV is a snapshot and
a deal can open the morning of the run.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable

ACTIVE_DAYS = 14

# Tags that mean a call is on the calendar. Kept in sync with the
# "0 - Do not contact check" step in both AI workflows.
BOOKED_TAGS = ("has upcoming call", "appt confirmed")


def _parse(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def booked_tag_hit(tags: Iterable[str]) -> str | None:
    """Return the booked-call tag the contact carries, or None."""
    lowered = {str(t).strip().lower() for t in (tags or [])}
    for tag in BOOKED_TAGS:
        if tag in lowered:
            return tag
    return None


def two_way_recently(messages: Iterable[dict], now: _dt.datetime | None = None,
                     days: int = ACTIVE_DAYS) -> bool:
    """True when the thread has inbound AND outbound traffic inside `days`.

    `messages` is the list GHL returns for a conversation; each item needs
    `direction` and `dateAdded`.
    """
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cutoff = now - _dt.timedelta(days=days)
    inbound = outbound = False
    for m in messages or []:
        when = _parse(m.get("dateAdded"))
        if when is None or when < cutoff:
            continue
        if m.get("direction") == "inbound":
            inbound = True
        elif m.get("direction") == "outbound":
            outbound = True
        if inbound and outbound:
            return True
    return False


def is_rep_working_them(contact: dict, messages: Iterable[dict],
                        now: _dt.datetime | None = None) -> str | None:
    """Reason to skip this contact, or None when the bot may have them.

    `contact` is the live GHL contact record, `messages` its SMS thread.
    """
    tag = booked_tag_hit(contact.get("tags") or [])
    if tag:
        return f"booked call ({tag})"
    if two_way_recently(messages, now=now):
        return f"two-way conversation in the last {ACTIVE_DAYS} days"
    return None
