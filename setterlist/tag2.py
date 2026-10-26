"""Tag the two new lists in the SMS sub-account."""
import os, sys, json
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient
c = GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"])
lists = json.load(open("new_lists.json"))
TAGS = {"fresh": "10/26 juan new leads", "showup": "10/26 juan webinar + newsletter"}
res = {}
for key, tag in TAGS.items():
    rows = [r for r in lists[key] if r["loc"] == "sms"]
    ok, failed = 0, []
    for r in rows:
        try:
            c.post(f"/contacts/{r['id']}/tags", {"tags": [tag]}); ok += 1
        except Exception as exc:
            failed.append((r["id"], r["name"], str(exc)[:100]))
    print(f"{tag}: tagged {ok} of {len(rows)}, failures {len(failed)}")
    for f in failed[:5]: print("   FAIL", f)
    res[tag] = {"tagged": ok, "failed": failed}
json.dump(res, open("tag2_result.json", "w"))
