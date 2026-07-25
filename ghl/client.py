"""Thin authenticated client for the GoHighLevel v2 API.

Credentials come from the environment, never from arguments or files:
    GHL_API_KEY      private integration token (starts with "pit-")
    GHL_LOCATION_ID  the sub-account this client is scoped to
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator

import requests

BASE_URL = "https://services.leadconnectorhq.com"
API_VERSION = "2021-07-28"

# Documented ceilings: 100 requests per 10s burst window, 200k per day.
# We pace below the burst limit rather than waiting to be told off.
BURST_LIMIT = 100
BURST_WINDOW_SECONDS = 10.0


class GHLError(RuntimeError):
    """An API call failed in a way retrying will not fix."""

    def __init__(self, status: int, method: str, path: str, body: str):
        self.status = status
        super().__init__(f"{method} {path} -> HTTP {status}: {body[:500]}")


class GHLClient:
    def __init__(self, token: str | None = None, location_id: str | None = None):
        self.token = token or os.environ.get("GHL_API_KEY", "")
        self.location_id = location_id or os.environ.get("GHL_LOCATION_ID", "")
        if not self.token:
            raise GHLError(0, "INIT", "-", "GHL_API_KEY is not set")
        if not self.location_id:
            raise GHLError(0, "INIT", "-", "GHL_LOCATION_ID is not set")
        if not self.token.startswith("pit-"):
            raise GHLError(
                0, "INIT", "-",
                "GHL_API_KEY does not look like a private integration token "
                "(expected a 'pit-' prefix). Legacy v1 API keys are rejected by the v2 API.",
            )

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Version": API_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        self._window_started = time.monotonic()
        self._window_count = 0

    # -- rate limiting -------------------------------------------------

    def _throttle(self) -> None:
        """Stay under the burst ceiling by sleeping out the window when full."""
        elapsed = time.monotonic() - self._window_started
        if elapsed >= BURST_WINDOW_SECONDS:
            self._window_started = time.monotonic()
            self._window_count = 0
        elif self._window_count >= BURST_LIMIT - 5:  # margin for other clients
            time.sleep(BURST_WINDOW_SECONDS - elapsed)
            self._window_started = time.monotonic()
            self._window_count = 0
        self._window_count += 1

    # -- transport -----------------------------------------------------

    def request(self, method: str, path: str, *, params: dict | None = None,
                json: dict | None = None, attempts: int = 4) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        delay = 2.0
        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                resp = self.session.request(method, url, params=params, json=json, timeout=45)
            except requests.RequestException as exc:
                if attempt == attempts:
                    raise GHLError(0, method, path, f"network error: {exc}") from exc
                time.sleep(delay)
                delay *= 2
                continue

            # 429 and 5xx are transient; everything else is a real answer.
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == attempts:
                    raise GHLError(resp.status_code, method, path, resp.text)
                time.sleep(float(resp.headers.get("Retry-After", delay)))
                delay *= 2
                continue

            if resp.status_code >= 400:
                raise GHLError(resp.status_code, method, path, resp.text)

            return resp.json() if resp.content else {}

        raise GHLError(0, method, path, "exhausted retries")

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        params.setdefault("locationId", self.location_id)
        return self.request("GET", path, params=params)

    def post(self, path: str, payload: dict) -> dict[str, Any]:
        return self.request("POST", path, json=payload)

    # -- reads used across the toolkit ---------------------------------

    def location(self) -> dict[str, Any]:
        return self.request("GET", f"/locations/{self.location_id}").get("location", {})

    def tags(self) -> list[dict]:
        return self.request("GET", f"/locations/{self.location_id}/tags").get("tags", [])

    def custom_fields(self) -> list[dict]:
        return self.request("GET", f"/locations/{self.location_id}/customFields").get("customFields", [])

    def workflows(self) -> list[dict]:
        """Workflows are read-only in the public API — there is no create/update endpoint."""
        return self.get("/workflows/").get("workflows", [])

    def email_schedules(self, limit: int = 100) -> list[dict]:
        return self.get("/emails/schedule", limit=limit).get("schedules", [])

    def email_templates(self, limit: int = 100) -> list[dict]:
        return self.get("/emails/builder", limit=limit).get("builders", [])

    def campaigns(self) -> list[dict]:
        return self.get("/campaigns/").get("campaigns", [])

    def search_contacts(self, filters: list[dict] | None = None,
                        sort: list[dict] | None = None,
                        page_limit: int = 100,
                        max_records: int | None = None) -> Iterator[dict]:
        """Page through POST /contacts/search, yielding contacts.

        Pagination uses the searchAfter cursor from the final contact of each
        page; offset paging is capped server-side and silently truncates.
        """
        payload: dict[str, Any] = {"locationId": self.location_id, "pageLimit": page_limit}
        if filters:
            payload["filters"] = filters
        payload["sort"] = sort or [{"field": "dateAdded", "direction": "desc"}]

        yielded = 0
        search_after = None
        while True:
            if search_after is not None:
                payload["searchAfter"] = search_after
            body = self.post("/contacts/search", payload)
            batch = body.get("contacts", [])
            if not batch:
                return
            for contact in batch:
                yield contact
                yielded += 1
                if max_records is not None and yielded >= max_records:
                    return
            search_after = batch[-1].get("searchAfter")
            if not search_after:
                return

    def count_contacts(self, filters: list[dict] | None = None) -> int:
        payload: dict[str, Any] = {"locationId": self.location_id, "pageLimit": 1}
        if filters:
            payload["filters"] = filters
        return int(self.post("/contacts/search", payload).get("total", 0))
