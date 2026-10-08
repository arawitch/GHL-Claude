"""Read registrant and attendance records out of WebinarJam / EverWebinar.

There is no webhook. Third-party guides claim a `POST /webhooks` endpoint with a
bearer token; that route does not exist, and neither does `/attendees`. Probing
the API with a deliberately wrong path (`/everwebinar/zzznotreal`) returns a 404
HTML page, while every real route answers
`{"errors":{"api_key":["The api key field is required."]}}` -- so the routes
below are confirmed, and the ones that 404 are confirmed absent:

    POST /webinarjam/webinars     POST /everwebinar/webinars
    POST /webinarjam/webinar      POST /everwebinar/webinar
    POST /webinarjam/register     POST /everwebinar/register
    POST /webinarjam/registrants  POST /everwebinar/registrants   <- attendance
    POST /webinarjam/zzznotreal   -> 404     (control)
    POST /webinarjam/attendees    -> 404     (does not exist)

Attendance therefore has to be polled, not received. `/registrants` carries the
same fields as the dashboard CSV export -- attended_live, time_live,
attended_replay, time_replay, purchased_live, revenue_live -- so polling it
replaces exporting a CSV by hand after every event.

Auth is an API key in the form-encoded body. Everything here is read-only.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator

import requests

BASE_URL = "https://api.webinarjam.com"

# The two products are separate APIs behind one key and one host. Live events
# live under webinarjam, evergreen / just-in-time under everwebinar, and a
# webinar_id is only meaningful within its own product.
LIVE = "webinarjam"
EVERGREEN = "everwebinar"


class WebinarJamError(RuntimeError):
    def __init__(self, path: str, status: int, body: str):
        self.status = status
        super().__init__(f"POST {path} -> HTTP {status}: {body[:400]}")


class WebinarJamClient:
    """Minimal client for the two endpoints attendance syncing needs."""

    def __init__(self, api_key: str | None = None, product: str = EVERGREEN):
        self.api_key = api_key or os.environ.get("WJ_API_KEY", "")
        if not self.api_key:
            raise WebinarJamError("-", 0, "WJ_API_KEY is not set")
        if product not in (LIVE, EVERGREEN):
            raise WebinarJamError("-", 0, f"product must be {LIVE!r} or {EVERGREEN!r}")
        self.product = product
        self.session = requests.Session()

    def _post(self, method: str, attempts: int = 4, **fields: Any) -> dict[str, Any]:
        path = f"/{self.product}/{method}"
        fields["api_key"] = self.api_key
        delay = 2.0
        for attempt in range(1, attempts + 1):
            try:
                r = self.session.post(f"{BASE_URL}{path}", data=fields, timeout=60)
            except requests.RequestException as exc:
                if attempt == attempts:
                    raise WebinarJamError(path, 0, f"network error: {exc}") from exc
                time.sleep(delay); delay *= 2
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == attempts:
                    raise WebinarJamError(path, r.status_code, r.text)
                time.sleep(delay); delay *= 2
                continue
            if r.status_code >= 400:
                raise WebinarJamError(path, r.status_code, r.text)
            body = r.json()
            # A 200 can still carry status:error -- an invalid key comes back
            # that way rather than as a 401.
            if body.get("status") == "error":
                raise WebinarJamError(path, r.status_code, str(body.get("errors")))
            return body
        raise WebinarJamError(path, 0, "exhausted retries")

    def webinars(self) -> list[dict]:
        return self._post("webinars").get("webinars", [])

    def webinar(self, webinar_id: int) -> dict:
        return self._post("webinar", webinar_id=webinar_id).get("webinar", {})

    def registrants(self, webinar_id: int) -> Iterator[dict]:
        """Every registrant for a webinar, following Laravel-style pagination.

        25 per page; `last_page` bounds the walk. Pages are requested in order
        rather than by cursor because that is all the endpoint offers.
        """
        page, last = 1, 1
        while page <= last:
            block = self._post("registrants", webinar_id=webinar_id,
                               page=page).get("registrants") or {}
            last = int(block.get("last_page") or 1)
            for row in (block.get("data") or []):
                yield row
            page += 1


# -- deriving a single state from the attendance flags --------------------

def state_of(row: dict) -> str:
    """One of attended / replay / absent.

    attended_live and attended_replay are independent "Yes"/"No" flags and both
    can be Yes. Live wins, because someone who sat through the live session and
    later reopened the replay is a live attendee -- that is the cohort whose
    conversion the revenue data measures.
    """
    if (row.get("attended_live") or "").strip().lower() == "yes":
        return "attended"
    if (row.get("attended_replay") or "").strip().lower() == "yes":
        return "replay"
    return "absent"


def watch_seconds(row: dict) -> int:
    """Seconds actually watched, live or replay, whichever is longer.

    Worth keeping separate from the state: a third of "replay watchers" log
    00:00:00, having opened the room and left. They are no warmer than a
    no-show and should not be messaged as though they saw the content.
    """
    best = 0
    for key in ("time_live", "time_replay"):
        parts = (row.get(key) or "").split(":")
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            h, m, s = (int(p) for p in parts)
            best = max(best, h * 3600 + m * 60 + s)
    return best


def purchased(row: dict) -> bool:
    return any((row.get(k) or "").strip().lower() == "yes"
               for k in ("purchased_live", "purchased_replay"))


def phone_of(row: dict) -> str | None:
    """E.164 phone, or None when the field holds something undialable.

    The registration form lets people type anything into the phone box, so this
    sees survey answers and bare hyphens as often as numbers. It also has to
    undo a "+1" that WebinarJam prepends to numbers which already carry their
    own country code -- "+1447932149848" is a UK mobile with a stray 1.
    """
    digits = "".join(c for c in (row.get("phone_number") or "") if c.isdigit())
    cc = (row.get("phone_country_code") or "").strip()
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
