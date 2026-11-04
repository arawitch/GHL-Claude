"""Turn the Meta ids in a contact's attribution into readable names.

Ads built after July 2026 append {{campaign.id}} / {{adset.id}} / {{ad.id}}
to the landing page instead of the matching .name macros, so GoHighLevel
stores 18-digit numbers where it used to store "JH Schedules - 10/9/26" and
"Ad 1 - Copy". The names are not lost: Meta ids are stable, so the numbers
decode against a lookup table (ghl/ad_id_map.json).

For each contact this writes, additively and only when it has something to
say:
  * a pinned-looking note, "Ad attribution", with platform, campaign,
    ad set, creative and landing page, which is what shows in the contact's
    timeline, and
  * the ad_name / campaign_id / ad_id / utm_* custom fields, which already
    existed in the sub-account and were sitting empty.

The note is what a human reads; the custom fields are what a workflow or an
export can filter on. A contact whose ad_name is already filled is skipped,
so re-running is safe and cheap.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ghl.client import GHLClient, GHLError

MAP_PATH = Path(__file__).with_name("ad_id_map.json")

NOTE_PREFIX = "Ad attribution"

# Fields that already exist in the SMS sub-account and were never populated.
FIELD_IDS = {
    "ad_name": "cpzNss3JDpswKmro4JUH",
    "ad_id": "4VLjuRPOLkG56iW4KeYW",
    "campaign_id": "Z0IAo9LONgOUtroc86p2",
    "utm_campaign": "8ezWZmjGUmQ6O6lL77C2",
    "utm_content": "CMzv8ww60c4VrTTOPcEp",
    "utm_source": "kkp6LnOiJbf0gv9bfUXe",
}

PLATFORM_NAMES = {"fb": "Facebook", "ig": "Instagram", "facebook": "Facebook",
                  "instagram": "Instagram", "msg": "Messenger", "an": "Audience Network"}


def load_map(path: Path | None = None) -> dict[str, dict[str, str]]:
    raw = json.loads((path or MAP_PATH).read_text())
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _is_id(value: str) -> bool:
    return bool(value) and value.isdigit() and len(value) > 10


def decode(attribution: dict[str, Any],
           table: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Return readable campaign / ad set / creative for one attributionSource.

    Returns None when there is nothing from an ad to decode, so that direct
    traffic, imports and DM conversations are left alone rather than annotated
    with blanks.
    """
    if not attribution:
        return None
    campaign = str(attribution.get("campaign") or "")
    ad = str(attribution.get("utmContent") or "")
    adset = str(attribution.get("utmTerm") or "")
    medium = str(attribution.get("utmMedium") or "")
    platform = str(attribution.get("utmSource") or "")
    if not (campaign or ad):
        return None

    # The pre-July ads already sent names, and put the ad set name in
    # utm_medium rather than utm_term. Keep those as they are.
    out = {
        "platform": PLATFORM_NAMES.get(platform.lower(), platform),
        "campaign": table["campaigns"].get(campaign, campaign),
        "adset": "",
        "creative": table["ads"].get(ad, ad),
        "campaign_id": campaign if _is_id(campaign) else "",
        "ad_id": ad if _is_id(ad) else "",
        "landing_page": str(attribution.get("url") or "").split("?")[0],
        "undecoded": "",
    }
    if medium and medium.lower() != "paid" and not _is_id(medium):
        out["adset"] = medium
    else:
        out["adset"] = table["adsets"].get(adset, adset)

    # Only flag an id that is still showing as a number after decoding; the
    # pre-July ads put the ad set *name* in utm_medium and an unrelated id in
    # utm_term, and that id never needs looking up.
    missing = [out[key] for key in ("campaign", "adset", "creative")
               if _is_id(str(out[key]))]
    out["undecoded"] = ",".join(dict.fromkeys(missing))
    return out


def note_body(decoded: dict[str, str]) -> str:
    lines = [f"{NOTE_PREFIX} (decoded from Meta ids)"]
    for label, key in (("Platform", "platform"), ("Campaign", "campaign"),
                       ("Ad set", "adset"), ("Creative", "creative"),
                       ("Landing page", "landing_page")):
        if decoded.get(key):
            lines.append(f"{label}: {decoded[key]}")
    if decoded.get("undecoded"):
        lines.append(f"Not in the lookup table yet: {decoded['undecoded']}")
    return "\n".join(lines)


def custom_field_payload(decoded: dict[str, str]) -> list[dict[str, str]]:
    values = {
        "ad_name": decoded.get("creative", ""),
        "ad_id": decoded.get("ad_id", ""),
        "campaign_id": decoded.get("campaign_id", ""),
        "utm_campaign": decoded.get("campaign", ""),
        "utm_content": decoded.get("creative", ""),
        "utm_source": decoded.get("platform", ""),
    }
    return [{"id": FIELD_IDS[name], "value": value}
            for name, value in values.items() if value]


def already_annotated(contact: dict[str, Any]) -> bool:
    """True when a previous run already filled ad_name on this contact."""
    for field in contact.get("customFields") or []:
        if field.get("id") == FIELD_IDS["ad_name"] and field.get("value"):
            return True
    return False


def annotate(client: GHLClient, contacts: Iterable[dict[str, Any]],
             table: dict[str, dict[str, str]],
             write_notes: bool = True, write_fields: bool = True,
             dry_run: bool = False) -> dict[str, Any]:
    """Decode and write. Returns counts plus the ids that need a lookup."""
    stats = {"seen": 0, "decoded": 0, "written": 0, "skipped_annotated": 0,
             "no_ad_attribution": 0, "failed": 0}
    undecoded: dict[str, int] = {}
    examples: list[str] = []

    for contact in contacts:
        stats["seen"] += 1
        decoded = decode(contact.get("attributionSource") or {}, table)
        if not decoded:
            stats["no_ad_attribution"] += 1
            continue
        stats["decoded"] += 1
        for bad in filter(None, decoded["undecoded"].split(",")):
            undecoded[bad] = undecoded.get(bad, 0) + 1
        if already_annotated(contact):
            stats["skipped_annotated"] += 1
            continue
        if len(examples) < 3:
            examples.append(note_body(decoded).replace("\n", " | "))
        if dry_run:
            continue
        cid = contact["id"]
        try:
            if write_fields:
                payload = custom_field_payload(decoded)
                if payload:
                    client.put(f"/contacts/{cid}", {"customFields": payload})
            if write_notes:
                client.post(f"/contacts/{cid}/notes", {"body": note_body(decoded)})
            stats["written"] += 1
        except GHLError as exc:
            stats["failed"] += 1
            if stats["failed"] <= 5:
                print(f"  ! {cid}: {exc}")

    return {"stats": stats, "undecoded": undecoded, "examples": examples}
