"""WebinarJam API client.

Verified against the live API. The registrants endpoint returns a Laravel
paginator, so the list lives under `registrants.data` rather than at the top
level, and `last_page` drives pagination.

One trap worth knowing: WebinarJam uses two different numbering schemes for the
same session. The one-click registration *link* takes the session number shown
in the webinar configuration (1, 2, 3 ...), while this API takes the global
schedule id (107, 108, ...). Passing the session number here returns an empty
result set with `status: success` rather than an error.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

BASE_URL = "https://api.webinarjam.com/webinarjam"

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
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("WEBINARJAM_API_KEY", "")
        if not self.api_key:
            raise WebinarJamError("WEBINARJAM_API_KEY is not set")
        self.session = requests.Session()
        self._last_call = 0.0

    def _post(self, path: str, **fields: Any) -> dict[str, Any]:
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - gap)
        payload = {"api_key": self.api_key, **fields}
        resp = self.session.post(f"{BASE_URL}{path}", data=payload, timeout=45)
        self._last_call = time.monotonic()
        if resp.status_code != 200:
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

    def has_run(self, webinar_id: int, schedule_id: int) -> bool | None:
        """Has this session already happened? None if the date cannot be read.

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
        return start < datetime.now(timezone.utc)

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

    def registrants(self, webinar_id: int, schedule_id: int) -> Iterator[dict]:
        """Yield every registrant for one session, following pagination."""
        page = 1
        while True:
            body = self._post("/registrants", webinar_id=webinar_id,
                              schedule_id=schedule_id, page=page)
            block = body.get("registrants") or {}
            rows = block.get("data") or []
            for row in rows:
                yield row
            last = block.get("last_page") or 1
            if page >= last or not rows:
                return
            page += 1


def classify(row: dict, stayed_minutes: int = 0, event_finished: bool = True) -> list[str]:
    """Map one registrant record onto the roles it qualifies for.

    Everyone in the list registered. Live attendance and replay viewing are
    independent -- a contact can be both. `absent` means registered and did not
    attend live, which is why the "if they miss the live" webhook is redundant.

    Before the session has run, WebinarJam reports attended_live as "No" for
    everyone, because nobody has attended anything yet. Deriving `absent` from
    that would mark every registrant a no-show days before the event and feed
    them into the replay sequence. When event_finished is False only the
    registration role is returned.
    """
    roles = ["register"]
    if not event_finished:
        return roles
    live = _yes(row.get("attended_live"))
    roles.append("attended" if live else "absent")
    if _yes(row.get("attended_replay")):
        roles.append("replay")
    if _yes(row.get("purchased_live")) or _yes(row.get("purchased_replay")):
        roles.append("purchased")
    if stayed_minutes and live and _seconds(row.get("time_live")) >= stayed_minutes * 60:
        roles.append("stayed")
    return roles
