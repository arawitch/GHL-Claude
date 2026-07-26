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
# in dndSettings, and a contact can be email-suppressed there while `dnd` is
# false -- checking `dnd` alone would mail every one of them.
#
# Per-channel DND is not a boolean. Statuses observed live in this location are
# "inactive" (DND off), "active" (DND on) and "permanent" (DND on, set by a hard
# opt-out such as an SMS STOP keyword). Only "inactive" is safe. The Email
# channel currently uses just active/inactive, but SMS and RCS both carry
# "permanent" here, so an Email entry could acquire it too -- and a guard that
# only excluded "active" would pass those straight into a send.
#
# Excluding is done with not_eq rather than by requiring status == "inactive".
# Verified against the live API: eq on any value the location does not use
# matches every contact rather than none, so a positive assertion silently
# stops filtering. not_eq is exact -- eq("active") + not_eq("active") sums to
# the full contact count.
EMAIL_DND_ON_STATUSES = ["active", "permanent"]

MAILABLE = [
    {"field": "email", "operator": "exists"},
    {"field": "dnd", "operator": "eq", "value": False},
    *[{"field": "dndSettings.Email.status", "operator": "not_eq", "value": s}
      for s in EMAIL_DND_ON_STATUSES],
]

# The tag column is named so GoHighLevel's importer will not auto-map it onto
# the Tags field. An earlier export used a plain "tags" header holding
# pipe-joined values; re-importing that file made GHL read each whole string as
# one tag name and created 6,638 junk tags in a single pass. The separator is
# " / " rather than "|" for the same reason.
EXPORT_COLUMNS = [
    "id", "firstName", "lastName", "email", "phone",
    "tags_REFERENCE_DO_NOT_IMPORT", "source", "dateAdded", "dateUpdated", "country", "city",
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
            row["tags_REFERENCE_DO_NOT_IMPORT"] = " / ".join(contact.get("tags") or [])
            writer.writerow(row)
            written += 1
    return written
