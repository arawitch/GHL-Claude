"""Copy the main-account webinar/newsletter people into the SMS sub-account, without duplicating."""
import os, sys, json, csv, datetime
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
import rules
rules.TODAY = datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc)
import build
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient

TAG = "10/26 juan webinar + newsletter"
PROV = "copied from main account"
sms = GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"])
rows = list(csv.DictReader(open("list-showup-main.csv")))
print("to copy:", len(rows))

build.load_stages()
contacts, convs, opps, events = build.load()
now = rules.TODAY
future_ids = {e["contactId"] for e in json.load(open("events.json"))
              if e.get("contactId") and e.get("startTime")
              and datetime.datetime.fromisoformat(e["startTime"]) > now
              and e.get("status") not in ("cancelled", "invalid")}

def find_in_sms(email, phone):
    for field, value in (("email", email), ("phone", phone)):
        if not value: continue
        r = sms.post("/contacts/search", {"locationId": sms.location_id, "pageLimit": 5,
                                          "filters": [{"field": field, "operator": "eq", "value": value}]})
        hits = r.get("contacts", [])
        if hits: return hits[0]
    return None

created, tagged_existing, skipped, failed = [], [], [], []
for i, r in enumerate(rows, 1):
    email, phone, name = (r["email"] or "").strip(), r["phone"], r["name"]
    try:
        hit = find_in_sms(email, phone)
    except Exception as exc:
        failed.append((name, f"lookup: {exc}"[:110])); continue
    if hit:
        # it is already in SMS: only tag it if it still passes every exclusion there
        olist = opps.get(("sms", hit["id"]), [])
        reason = (build.dnd_blocked(hit) or build.owned(hit, olist) or build.dead(hit, olist)
                  or build.future_appt(hit, olist, future_ids))
        if reason:
            skipped.append((name, f"already in SMS and excluded: {reason}")); continue
        try:
            sms.post(f"/contacts/{hit['id']}/tags", {"tags": [TAG]})
            tagged_existing.append((name, hit["id"]))
        except Exception as exc:
            failed.append((name, f"tag: {exc}"[:110]))
        continue
    first, _, last = name.partition(" ")
    payload = {"locationId": sms.location_id, "firstName": first or name, "lastName": last,
               "email": email or None, "phone": phone,
               "source": "copied from main account for 10/26 call list",
               "tags": [TAG, PROV]}
    payload = {k: v for k, v in payload.items() if v not in (None, "")}
    try:
        res = sms.post("/contacts/upsert", payload)
        ct = res.get("contact") or {}
        created.append((name, ct.get("id"), res.get("new")))
    except Exception as exc:
        failed.append((name, f"create: {exc}"[:110]))
    if i % 25 == 0: print("processed", i, flush=True)

print("\ncreated in SMS:", len(created))
print("already there, tagged:", len(tagged_existing))
print("skipped:", len(skipped))
for s in skipped: print("   ", s[0], "|", s[1])
print("failed:", len(failed))
for f in failed[:10]: print("   ", f)
json.dump({"created": created, "tagged_existing": tagged_existing,
           "skipped": skipped, "failed": failed}, open("copy_main_result.json", "w"))
