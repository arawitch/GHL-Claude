"""Add the call-list tag to the picked contacts that live in the SMS sub-account."""
import os, sys, json
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient
TAG = "10/19 juan call list"
c = GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"])
picked = json.load(open("picked.json"))
sms = [p for p in picked if p["loc"] == "sms"]
ok = 0; failed = []
for i, p in enumerate(sms, 1):
    try:
        c.post(f"/contacts/{p['id']}/tags", {"tags": [TAG]})
        ok += 1
    except Exception as exc:
        failed.append((p["id"], p["name"], str(exc)[:120]))
    if i % 50 == 0: print("tagged", i, flush=True)
print("tagged:", ok, "of", len(sms), "| failures:", len(failed))
for f in failed[:10]: print("  FAIL", f)
json.dump({"tag": TAG, "tagged": ok, "failed": failed}, open("tag_result.json", "w"))
