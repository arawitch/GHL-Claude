"""Dump custom field definitions for both sub-accounts."""
import os, json, requests
B = "https://services.leadconnectorhq.com"
for label in ("SMS", "EMAIL"):
    tok = os.environ[f"GHL_{label}_API_KEY"]
    loc = os.environ[f"GHL_{label}_LOCATION_ID"]
    h = {"Authorization": f"Bearer {tok}", "Version": "2021-07-28", "Accept": "application/json"}
    r = requests.get(f"{B}/locations/{loc}/customFields", headers=h, timeout=60)
    r.raise_for_status()
    cf = r.json().get("customFields", [])
    json.dump(cf, open(f"cf_{label}.json", "w"))
    print(label, loc, len(cf), "custom fields")
