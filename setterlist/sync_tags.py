"""Make the SMS tags match the rebuilt lists exactly, creating the handful that have no SMS record."""
import os, sys, json, csv
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient
c = GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"])
FRESH, SHOW = "10/26 juan new leads", "10/26 juan webinar + newsletter"
PROV = "copied from main account"
lists = json.load(open("new_lists.json"))

def members(tag):
    return {ct["id"] for ct in c.search_contacts(
        filters=[{"field": "tags", "operator": "eq", "value": tag}])}

def create_in_sms(row, tag):
    name = row["name"]; first, _, last = name.partition(" ")
    payload = {"locationId": c.location_id, "firstName": first or name, "lastName": last,
               "email": (row["email"] or "").strip() or None, "phone": row["phone"],
               "source": "copied from main account for 10/26 call list",
               "tags": [tag, PROV]}
    res = c.post("/contacts/upsert", {k: v for k, v in payload.items() if v not in (None, "")})
    return (res.get("contact") or {}).get("id")

report = {}
# the people with no SMS record at all: create them, since Audry asked for them in SMS
created = []
for row in csv.DictReader(open("list-showup-main.csv")):
    try:
        cid = create_in_sms(row, SHOW); created.append((row["name"], cid))
    except Exception as exc:
        print("create failed", row["name"], str(exc)[:110])
print("created in SMS:", len(created))
report["created"] = created

for tag, key in ((FRESH, "fresh"), (SHOW, "showup")):
    want = {r["id"] for r in lists[key] if r["loc"] == "sms"}
    if tag == SHOW: want |= {cid for _, cid in created if cid}
    have = members(tag)
    add, drop = want - have, have - want
    for cid in add:
        try: c.post(f"/contacts/{cid}/tags", {"tags": [tag]})
        except Exception as exc: print("tag failed", cid, str(exc)[:90])
    for cid in drop:
        try: c.request("DELETE", f"/contacts/{cid}/tags", json={"tags": [tag]})
        except Exception as exc: print("untag failed", cid, str(exc)[:90])
    final = members(tag)
    print(f"{tag}: wanted {len(want)}, added {len(add)}, removed {len(drop)}, now {len(final)}, "
          f"matches: {final == want}")
    report[tag] = {"wanted": len(want), "added": len(add), "removed": len(drop),
                   "final": len(final), "exact": final == want}
json.dump(report, open("sync_result.json", "w"))
