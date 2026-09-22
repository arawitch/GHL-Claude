"""Rank bulk email sends by engagement.

Two data sources, because GoHighLevel splits them:

  /emails/schedule            what was sent, to how many, and how many landed
  Email Statistics V2         who opened and clicked

The schedule endpoint carries no engagement fields at all, so a ranking needs
both. They are joined on the schedule's own id.

Everything here is read-only.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from .client import GHLClient, GHLError, GHLScopeError

# Below this, a send is a segment test or a one-off, not a bulk campaign.
BULK_MIN_RECIPIENTS = 3000

# The statistics endpoint is not in the public scope listings and its path has
# moved between API versions, so it is discovered rather than hardcoded. Paths
# that 404 do not exist; a 401 means the path is real and the token is missing
# a scope -- the two are distinguished so the error can say which it is.
STATS_PATHS = [
    "/emails/campaigns/{id}/statistics",
    "/emails/schedule/{id}/statistics",
    "/emails/statistics/{id}",
]

# GHL has used several spellings for the same counter across versions. Each
# metric maps to the candidate keys in priority order; the first one present
# wins. "unique" variants are preferred because a rate built on total opens can
# exceed 100% and is not comparable between sends.
METRIC_KEYS: dict[str, list[str]] = {
    "delivered":   ["delivered", "totalDelivered", "deliveredCount", "sent", "successCount"],
    "opens":       ["uniqueOpens", "uniqueOpened", "opened", "opens", "totalOpens", "openCount"],
    "clicks":      ["uniqueClicks", "uniqueClicked", "clicked", "clicks", "totalClicks", "clickCount"],
    "bounces":     ["bounced", "bounces", "totalBounced", "bounceCount"],
    "unsubscribes": ["unsubscribed", "unsubscribes", "optOuts", "unsubscribeCount"],
    "complaints":  ["complained", "complaints", "spamReports", "complaintCount"],
    "replies":     ["replied", "replies", "replyCount"],
}


def _epoch_ms_to_dt(value: Any) -> dt.datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return dt.datetime.utcfromtimestamp(value / 1000)
    return None


def sent_at(schedule: dict) -> dt.datetime | None:
    """When a send actually went out, preferring the scheduled time."""
    for key in ("dateScheduled", "dateAdded", "createdAt"):
        stamp = _epoch_ms_to_dt(schedule.get(key))
        if stamp:
            return stamp
    return None


def has_usable_counters(schedule: dict) -> bool:
    """Whether this record's delivery counters were ever populated.

    Records written by the v1 bulk action pipeline leave processed and
    successCount at zero and park everything in queuedCount. Reading those as
    "nothing was delivered" understates old campaigns to zero, so they are
    marked rather than silently ranked last.
    """
    return schedule.get("bulkActionVersion") == "v2" and (schedule.get("processed") or 0) > 0


def bulk_sends(client: GHLClient, since: dt.datetime | None = None,
               min_recipients: int = BULK_MIN_RECIPIENTS,
               page_limit: int = 100) -> list[dict]:
    """Completed sends at or above the bulk threshold, newest first."""
    out, offset = [], 0
    seen: set[str] = set()
    while True:
        body = client.get("/emails/schedule", limit=page_limit, offset=offset)
        batch = body.get("schedules") or []
        if not batch:
            break
        fresh = [b for b in batch if b.get("id") not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add(row.get("id"))
            when = sent_at(row)
            if row.get("status") != "complete":
                continue
            if (row.get("totalCount") or 0) < min_recipients:
                continue
            if since and (when is None or when < since):
                continue
            out.append(row)
        offset += page_limit
    return sorted(out, key=lambda r: sent_at(r) or dt.datetime.min, reverse=True)


def discover_stats_path(client: GHLClient, email_id: str) -> str:
    """Find the statistics path this account exposes.

    Raises GHLScopeError if a real path exists but the token cannot use it,
    which is a different problem from the endpoint being absent and needs a
    different fix -- regenerating the token rather than changing the code.
    """
    scope_blocked = []
    for template in STATS_PATHS:
        path = template.format(id=email_id)
        try:
            client.get(path)
            return template
        except GHLScopeError:
            scope_blocked.append(template)
        except GHLError as exc:
            if exc.status != 404:
                raise
    if scope_blocked:
        raise GHLScopeError(
            401, "GET", scope_blocked[0].format(id=email_id),
            '{"message":"The token is not authorized for this scope."}')
    raise GHLError(404, "GET", "/emails/.../statistics", "",
                   hint="No statistics endpoint responded. Tried: "
                        + ", ".join(STATS_PATHS))


def extract_metrics(payload: Any) -> dict[str, int]:
    """Pull engagement counters out of a statistics response.

    The response shape is not pinned down in public documentation and differs
    between API versions, so this walks whatever nesting it is given and takes
    the first recognised spelling of each counter.
    """
    flat: dict[str, Any] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    flat.setdefault(key, value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    lowered = {k.lower(): v for k, v in flat.items()}
    metrics: dict[str, int] = {}
    for metric, candidates in METRIC_KEYS.items():
        for candidate in candidates:
            if candidate.lower() in lowered:
                metrics[metric] = int(lowered[candidate.lower()])
                break
    return metrics


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if not denominator or numerator is None:
        return None
    return 100.0 * numerator / denominator


def build_rows(client: GHLClient, schedules: Iterable[dict]) -> list[dict]:
    """Join each send with its statistics. Never raises for one bad campaign."""
    schedules = list(schedules)
    if not schedules:
        return []
    template = discover_stats_path(client, schedules[0]["id"])

    rows = []
    for schedule in schedules:
        row = {
            "id": schedule.get("id"),
            "date": sent_at(schedule),
            "name": schedule.get("name"),
            "subject": schedule.get("subject"),
            "recipients": schedule.get("totalCount") or 0,
            "counters_usable": has_usable_counters(schedule),
            "error": "",
        }
        try:
            metrics = extract_metrics(client.get(template.format(id=schedule["id"])))
        except GHLError as exc:
            metrics, row["error"] = {}, str(exc).splitlines()[0]

        # Prefer the statistics endpoint's own delivered figure; fall back to
        # the schedule's successCount, which measures the same thing.
        delivered = metrics.get("delivered") or (schedule.get("successCount") or 0)
        row.update(metrics)
        row["delivered"] = delivered
        row["open_rate"] = _rate(metrics.get("opens"), delivered)
        row["click_rate"] = _rate(metrics.get("clicks"), delivered)
        # Click-to-open separates "the subject line worked" from "the email
        # worked", which a click rate alone conflates.
        row["cto_rate"] = _rate(metrics.get("clicks"), metrics.get("opens"))
        rows.append(row)
    return rows


def rank(rows: Iterable[dict], by: str = "open_rate", top: int | None = None) -> list[dict]:
    """Rank by a rate, dropping sends whose rate could not be computed.

    A send with no delivery data is excluded rather than sorted to the bottom:
    absent data and genuinely zero engagement are different findings, and
    ranking them together quietly turns the first into the second.
    """
    scored = [r for r in rows if r.get(by) is not None]
    scored.sort(key=lambda r: r[by], reverse=True)
    return scored[:top] if top else scored
