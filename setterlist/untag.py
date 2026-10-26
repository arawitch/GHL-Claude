"""Take the new tag off anyone who is already on the 10/19 list or already dialled."""
import os, sys, json, csv
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient
TAG = "10/26 juan webinar + newsletter"
c = GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"])
res = json.load(open("copy_main_result.json"))
old = {r["contact id"]: r["name"] for r in csv.DictReader(open("juan-call-list.csv"))}
dialled = set(json.load(open("week1.json"))["dialled"])
overlap = [(n, i) for n, i in res["tagged_existing"] if i in old or i in dialled]
print("overlapping with last week's list:", len(overlap))
removed, failed = [], []
for name, cid in overlap:
    try:
        c.request("DELETE", f"/contacts/{cid}/tags", json={"tags": [TAG]})
        removed.append((name, cid, "already dialled" if cid in dialled else "on the 10/19 list"))
    except Exception as exc:
        failed.append((name, cid, str(exc)[:110]))
for r in removed: print("   untagged", r[0], "|", r[2])
print("removed:", len(removed), "failed:", len(failed))
for f in failed: print("   FAIL", f)
json.dump({"removed": removed, "failed": failed}, open("untag_result.json", "w"))
