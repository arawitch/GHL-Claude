"""WebinarJam / EverWebinar API client.

Verified against the live API. The registrants endpoint returns a Laravel
paginator, so the list lives under `registrants.data` rather than at the top
level, and `last_page` drives pagination.

One trap worth knowing: WebinarJam uses two different numbering schemes for the
same session. The one-click registration *link* takes the session number shown
in the webinar configuration (1, 2, 3 ...), while this API takes the global
schedule id (107, 108, ...). Passing the session number here returns an empty
result set with `status: success` rather than an error.

**Two products, two APIs, one key.** Live events live under `/webinarjam`,
evergreen and just-in-time rooms under `/everwebinar`, and a webinar_id only
means something inside its own product -- this account has a live "Bot Webinar"
at id 2 and an evergreen one at id 7. An evergreen room reports its schedule as
the literal string "Just in time" with no date and no schedule id, so the
has_run / settle-minutes machinery below does not apply to it: a just-in-time
session is always already over for whoever registered.

**There is no webhook.** Third-party guides describe a `POST /webhooks` endpoint
with a bearer token; it does not exist, and neither does `/attendees`. Probing
with a deliberately wrong path settles it in both directions -- a fake route
returns a 404 HTML page while every real route returns
`{"errors":{"api_key":["The api key field is required."]}}`:

    POST /{product}/webinars, /webinar, /register, /registrants   exist
    POST /{product}/attendees, /webhooks, /zzznotreal (control)   404

So attendance is polled, not received, which is what this module is for.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

API_HOST = "https://api.webinarjam.com"
LIVE = "webinarjam"
EVERGREEN = "everwebinar"
BASE_URL = f"{API_HOST}/{LIVE}"      # kept for callers that predate --product

# Documented ceiling is 20 requests/second. We pace well under it -- nothing
# here is latency-sensitive and a 429 costs more than the delay saves.
MIN_INTERVAL_SECONDS = 0.1


class WebinarJamError(RuntimeError):
    pass


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in ("yes", "1", "true")


def _seconds(hhmmss: Any) -> int:
    """'00:13:51' -> 831. Returns 0 for anything unparseable."""
    parts = str(hhmmss or "").split(":")
    if len(parts) != 3:
        return 0
    try:
        h, m, s = (int(p) for p in parts)
    except ValueError:
        return 0
    return h * 3600 + m * 60 + s


class WebinarJamClient:
    def __init__(self, api_key: str | None = None, product: str = LIVE):
        # WJ_API_KEY is accepted as an alias because the GitHub Action was
        # written against that name. The key is shared across both products.
        self.api_key = (api_key or os.environ.get("WEBINARJAM_API_KEY")
                        or os.environ.get("WJ_API_KEY", ""))
        if not self.api_key:
            raise WebinarJamError(
                "WEBINARJAM_API_KEY is not set (WJ_API_KEY also accepted)")
        if product not in (LIVE, EVERGREEN):
            raise WebinarJamError(f"product must be {LIVE!r} or {EVERGREEN!r}, got {product!r}")
        self.product = product
        self.base_url = f"{API_HOST}/{product}"
        self.session = requests.Session()
        self._last_call = 0.0

    @property
    def evergreen(self) -> bool:
        return self.product == EVERGREEN

    def _post(self, path: str, **fields: Any) -> dict[str, Any]:
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        payload = {"api_key": self.api_key, **fields}
        resp = self.session.post(f"{self.base_url}{path}", data=payload, timeout=45)
        self._last_call = time.monotonic()
        if resp.status_code != 200:
            # A regenerated key does not 404 or say "invalid" -- the old one
            # answers "API access is not allowed!", which reads like a plan or
            # permissions problem rather than a stale credential. Regenerating
            # the key in WebinarJam silently invalidates every copy of it, so
            # this is what a sync looks like after someone rotates it and
            # forgets the environment variable.
            if "API access is not allowed" in resp.text:
                raise WebinarJamError(
                    f"POST {path} -> HTTP {resp.status_code}: this API key is not "
                    "accepted. A key regenerated in WebinarJam invalidates the old "
                    "one immediately, so check WEBINARJAM_API_KEY against "
                    "My Webinars > Advanced Settings > API custom integration.")
            raise WebinarJamError(f"POST {path} -> HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if body.get("status") != "success":
            raise WebinarJamError(f"POST {path} -> {str(body)[:300]}")
        return body

    def webinars(self) -> list[dict]:
        return self._post("/webinars").get("webinars", [])

    def webinar(self, webinar_id: int) -> dict:
        return self._post("/webinar", webinar_id=webinar_id).get("webinar", {})

    def schedules(self, webinar_id: int) -> list[dict]:
        """[{schedule: 107, date: '2026-07-30 14:00', comment: ...}, ...]"""
        return self.webinar(webinar_id).get("schedules", [])

    def has_run(self, webinar_id: int, schedule_id: int,
                after_minutes: int = 0) -> bool | None:
        """Has this session finished? None if the date cannot be read.

        `after_minutes` is how long after the start time attendance can be
        trusted. It matters because the API exposes a start time and no
        duration, so "has started" is the only thing directly knowable -- and
        acting on that tags everyone who has not joined *yet* as absent while
        the session is still running. Someone joining at 2:30 then carries both
        `attended` and `absent`, and the no-show follow-up is wrong for them.
        Set it past the longest the session ever runs.

        The `date` on a schedule carries no offset and is in the webinar's own
        timezone, which the webinar record exposes separately. Comparing it to a
        naive `datetime.now()` is wrong wherever the process clock is not in that
        timezone -- and this one runs in UTC. On 2026-07-30 that made a 2 PM
        Pacific session read as finished from 7 AM Pacific onward, seven hours
        early, and tagged all 64 registrants `absent` before it started.

        Returning None rather than True on an unreadable date matters: the caller
        must not guess "finished" and write attendance tags off a guess.
        """
        webinar = self.webinar(webinar_id)
        zone = webinar.get("timezone") or "UTC"
        raw = ""
        for s in webinar.get("schedules", []):
            if str(s.get("schedule")) == str(schedule_id):
                raw = str(s.get("date", ""))
        if not raw:
            return None
        try:
            naive = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            start = naive.replace(tzinfo=ZoneInfo(zone))
        except (ValueError, ZoneInfoNotFoundError):
            return None
        return start + timedelta(minutes=after_minutes) < datetime.now(timezone.utc)

    def register(self, webinar_id: int, schedule_id: int, email: str,
                 first_name: str, last_name: str = "", phone: str = "",
                 phone_country_code: str = "", country: str = "") -> dict:
        """Register one person for a session.

        The register endpoint names the session parameter `schedule`, while the
        registrants endpoint calls the same value `schedule_id`. Both take the
        global schedule id rather than the session number used by one-click
        links.

        WebinarJam is idempotent here: registering an address that is already
        registered returns success without creating a duplicate.
        """
        fields = {
            "webinar_id": webinar_id,
            "schedule": schedule_id,
            "email": email,
            "first_name": first_name or email.split("@")[0],
        }
        if last_name:
            fields["last_name"] = last_name
        if phone:
            fields["phone"] = phone
            fields["phone_country_code"] = phone_country_code or "+1"
        if country:
            fields["country"] = country
        return self._post("/register", **fields)

    def registrants(self, webinar_id: int, schedule_id: int | None = None,
                    schedule_contains: str | None = None) -> Iterator[dict]:
        """Yield every registrant, following pagination.

        `schedule_id` is omitted for an evergreen room, which has no scheduled
        sessions to address. For a live webinar it is required in practice:
        a webinar_id spans every session ever run under it -- id 2 here holds
        both the 9/24 and 10/1 events in one list of 198 -- so without it two
        events' registrants arrive together and land under one tag prefix.

        `schedule_contains` filters on the human-readable `schedule` string as a
        fallback for the same problem, useful when the global schedule id is not
        to hand.
        """
        page = 1
        needle = (schedule_contains or "").lower()
        while True:
            fields = {"webinar_id": webinar_id, "page": page}
            if schedule_id is not None:
                fields["schedule_id"] = schedule_id
            body = self._post("/registrants", **fields)
            block = body.get("registrants") or {}
            rows = block.get("data") or []
            for row in rows:
                if needle and needle not in (row.get("schedule") or "").lower():
                    continue
                yield row
            last = block.get("last_page") or 1
            if page >= last or not rows:
                return
            page += 1


# A room opened and immediately closed is not a view. Of the 10/1 replay
# viewers, 4 of 10 logged 00:00:00 -- and on the 30-day revenue numbers, replay
# watchers convert at 6.5% against 1.4% for registrants who never watched
# anything, so putting a zero-second open in the replay cohort hands a no-show
# the warmest follow-up in the sequence.
MIN_VIEW_SECONDS = 120


def classify(row: dict, stayed_minutes: int = 0, event_finished: bool = True,
             min_view_seconds: int = MIN_VIEW_SECONDS) -> list[str]:
    """Map one registrant record onto the roles it qualifies for.

    Everyone in the list registered. Live attendance and replay viewing are
    independent -- a contact can be both. `absent` means registered and did not
    attend live, which is why the "if they miss the live" webhook is redundant.

    Before the session has run, WebinarJam reports attended_live as "No" for
    everyone, because nobody has attended anything yet. Deriving `absent` from
    that would mark every registrant a no-show days before the event and feed
    them into the replay sequence. When event_finished is False only the
    registration role is returned.

    An `attended_live` or `attended_replay` of "Yes" with a watch time under
    `min_view_seconds` does not earn the role: the flag records that the room
    was entered, not that anything was seen.
    """
    roles = ["register"]
    if not event_finished:
        return roles
    live = _yes(row.get("attended_live")) and \
        _seconds(row.get("time_live")) >= min_view_seconds
    roles.append("attended" if live else "absent")
    if _yes(row.get("attended_replay")) and \
            _seconds(row.get("time_replay")) >= min_view_seconds:
        roles.append("replay")
    if _yes(row.get("purchased_live")) or _yes(row.get("purchased_replay")):
        roles.append("purchased")
    if stayed_minutes and live and _seconds(row.get("time_live")) >= stayed_minutes * 60:
        roles.append("stayed")
    return roles


def phone_of(row: dict) -> str | None:
    """E.164 phone from a registrant row, or None when it is undialable.

    The registration form accepts free text in the phone box, so this sees
    survey answers and bare hyphens as often as numbers. It also has to undo a
    "+1" WebinarJam prepends to numbers that already carry their own country
    code: "+1447932149848" is a UK mobile with a stray 1, and 15 of these went
    into GHL before anyone noticed.
    """
    digits = "".join(c for c in str(row.get("phone_number") or "") if c.isdigit())
    cc = str(row.get("phone_country_code") or "").strip()
    if cc.startswith("+") and cc != "+1":
        intl = cc.lstrip("+") + digits
        return "+" + intl if 10 <= len(intl) <= 15 else None
    if len(digits) == 10 and digits[0] in "23456789":
        return "+1" + digits
    if len(digits) == 11 and digits[0] == "1" and digits[1] in "23456789":
        return "+" + digits
    if 11 <= len(digits) <= 15 and not digits.startswith("1"):
        return "+" + digits
    return None
