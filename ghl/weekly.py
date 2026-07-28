"""Per-webinar audience segments for a two-track send plan.

The weekly webinar runs at a fixed time, so every send slot is knowable in
advance and can be a scheduled broadcast rather than a workflow. What changes
between slots is not the timing but the audience, and the two audiences want
opposite things:

  Track A -- registered. Wants logistics: confirmation, reminders, the join
             link. High frequency is welcome here; they asked to be there.
  Track B -- not registered. Wants persuasion: the hook, the angle, social
             proof, a last call. Frequency must be lower, and every send must
             exclude anyone who has since registered.

Both tracks run in parallel all week. A contact moves from B to A the moment
they register, and the segments here are mutually exclusive by construction so
nobody receives both versions of the same message.
"""

from __future__ import annotations

from .client import GHLClient
from .segments import all_of, has_tag
from .sending import engaged, not_tagged

# Suffixes appended to an event key, e.g. "7/24" -> "7/24 register".
# Override per call if a given week used different wording.
DEFAULT_SUFFIXES = {
    "register": "register",
    "attended": "attended",
    "absent": "absent",
    "replay": "replay",
}


def _tag(event: str, role: str, suffixes: dict[str, str] | None = None) -> str:
    return f"{event} {(suffixes or DEFAULT_SUFFIXES)[role]}"


def registered(event: str, suffixes=None) -> list[dict]:
    """Track A. Everyone signed up for this event."""
    return all_of(has_tag(_tag(event, "register", suffixes)))


def unregistered(event: str, suffixes=None) -> list[dict]:
    """Track B. The engaged send list minus anyone already registered.

    Built on engaged() so suppression and DND handling are inherited rather
    than reimplemented -- a registrant who opted out still must not be mailed.
    """
    return engaged(not_tagged(_tag(event, "register", suffixes)))


def no_shows(event: str, suffixes=None) -> list[dict]:
    """Registered but did not attend. The largest post-event opportunity."""
    return all_of(has_tag(_tag(event, "absent", suffixes)))


def attendees(event: str, suffixes=None) -> list[dict]:
    """Attended live. The warmest segment you will have all week."""
    return all_of(has_tag(_tag(event, "attended", suffixes)))


def non_openers(event: str, open_tag: str, suffixes=None) -> list[dict]:
    """Track B members who did not open a specific earlier send.

    open_tag is whichever tag that campaign applied on open, so this only
    works for sends configured to tag opens.
    """
    return engaged(
        not_tagged(_tag(event, "register", suffixes)),
        not_tagged(open_tag),
    )


# WebinarJam sends its own registrant reminders at 48h, 24h, 1h and 15min, each
# carrying that registrant's unique join link. Duplicating those in GHL would
# double-message the people most likely to attend, and GHL cannot reproduce the
# per-registrant link anyway. So the default plan cedes pre-event Track A to
# WebinarJam and keeps only what WebinarJam does not do: persuading people who
# have not registered, and everything after the event ends.
#
# Three of the six sends land on Thursday. That is not aggression for its own
# sake -- it is what their own archive shows works. Every past event with
# above-average clicks ran the same shape: a Wednesday "tomorrow at 2", a
# Thursday morning "we're live today", a Thursday midday "will you be joining
# at 2?", and a "going live in 15 mins". The midday and 15-minute sends are the
# shortest emails they send and among the best-clicking.
#
# wed-registered-primer is Track A but does not duplicate WebinarJam: it carries
# no join link and no logistics, only a question to sit with before the event.
SLOTS_WEBINARJAM = [
    ("mon-invite-1",           "B", unregistered),
    ("tue-invite-2",           "B", unregistered),
    ("wed-invite-3",           "B", unregistered),
    ("wed-registered-primer",  "A", registered),
    ("thu-am-invite",          "B", unregistered),
    ("thu-noon-invite",        "B", unregistered),
    ("thu-15min-invite",       "B", unregistered),
    ("thu-replay",             "-", no_shows),
    ("fri-replay-final",       "-", no_shows),
    ("fri-attendee-next",      "-", attendees),
]

# Use this only if WebinarJam's reminders are disabled or land in spam. Verify
# before switching: if both are live, registrants get two sets of reminders.
SLOTS_GHL_REMINDERS = SLOTS_WEBINARJAM[:4] + [
    ("thu-reminder-1h",        "A", registered),
    ("thu-live-now",           "A", registered),
] + SLOTS_WEBINARJAM[4:]

SLOTS = SLOTS_WEBINARJAM


def slots_for(reminders: str = "webinarjam"):
    return SLOTS_GHL_REMINDERS if reminders == "ghl" else SLOTS_WEBINARJAM


def plan(client: GHLClient, event: str, suffixes=None,
         reminders: str = "webinarjam") -> list[tuple[str, str, int]]:
    """Return (slot, track, recipient count) for each send in the week."""
    out = []
    for slot, track, builder in slots_for(reminders):
        try:
            n = client.count_contacts(builder(event, suffixes))
        except Exception:
            n = -1
        out.append((slot, track, n))
    return out
