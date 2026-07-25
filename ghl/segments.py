"""Build targeted lead lists out of contact search filters.

A segment is a named, reusable filter definition. Definitions live in
segments.yaml so a list can be re-run later instead of rebuilt by hand.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .client import GHLClient

# Contacts that cannot legally or technically receive a marketing email.
# Every email-bound segment should be intersected with this.
#
# The global `dnd` flag is not enough. GoHighLevel also tracks DND per channel
# in dndSettings, where a status of "active" means DND is ON for that channel.
# 3,700 contacts in this location have dndSettings.Email.status == "active"
# while dnd is false -- email-suppressed without the global flag set. Checking
# `dnd` alone would mail every one of them.
MAILABLE = [
    {"field": "email", "operator": "exists"},
    {"field": "dnd", "operator": "eq", "value": False},
    {"field": "dndSettings.Email.status", "operator": "not_eq", "value": "active"},
]

EXPORT_COLUMNS = [
    "id", "firstName", "lastName", "email", "phone",
    "tags", "source", "dateAdded", "dateUpdated", "country", "city",
]


def has_tag(tag: str) -> dict:
    return {"field": "tags", "operator": "eq", "value": tag}


def any_tag(tags: Iterable[str]) -> dict:
    return {"group": "OR", "filters": [has_tag(t) for t in tags]}


def added_between(start: str, end: str) -> dict:
    """Inclusive ISO date range, e.g. added_between("2026-01-01", "2026-06-30").

    Both endpoints are whole days and both are included.

    Timezone caveat, verified against the live API: the filter is evaluated in
    the *location's* timezone (America/Los_Angeles), while the dateAdded field
    is returned in UTC. A contact stamped 2026-07-25T06:03Z is 23:03 on
    2026-07-24 locally and will NOT match a range starting 2026-07-25. Segment
    by local dates, not by the UTC timestamps you see in exports.
    """
    return {"field": "dateAdded", "operator": "range", "value": {"gte": start, "lte": end}}


def all_of(*filters: dict) -> list[dict]:
    """Combine filters with AND, flattening the mailable helper list."""
    flat: list[dict] = []
    for f in filters:
        flat.extend(f) if isinstance(f, list) else flat.append(f)
    return [{"group": "AND", "filters": flat}]


def mailable(*filters: dict) -> list[dict]:
    """AND the given filters with the mailability guard."""
    return all_of(*filters, MAILABLE)


class SegmentStore:
    """Named segment definitions persisted to a JSON/YAML-ish file."""

    def __init__(self, path: str | Path = "segments.json"):
        self.path = Path(path)
        self.segments: dict[str, Any] = {}
        if self.path.exists():
            self.segments = json.loads(self.path.read_text())

    def save(self, name: str, filters: list[dict], description: str = "") -> None:
        self.segments[name] = {"description": description, "filters": filters}
        self.path.write_text(json.dumps(self.segments, indent=2) + "\n")

    def get(self, name: str) -> list[dict]:
        if name not in self.segments:
            raise KeyError(f"no segment named {name!r}; known: {sorted(self.segments)}")
        return self.segments[name]["filters"]

    def names(self) -> list[str]:
        return sorted(self.segments)


def export_csv(client: GHLClient, filters: list[dict], out_path: str | Path,
               max_records: int | None = None) -> int:
    """Write a segment to CSV. Returns the row count written."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPORT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for contact in client.search_contacts(filters=filters, max_records=max_records):
            row = {k: contact.get(k, "") for k in EXPORT_COLUMNS}
            if isinstance(row.get("tags"), list):
                row["tags"] = "|".join(row["tags"])
            writer.writerow(row)
            written += 1
    return written
