"""The part of the 10/19 list Juan has not dialled yet, still ranked."""
import json, csv, datetime
week1 = json.load(open("week1.json"))
dialled = set(week1["dialled"])
ev = json.load(open("events.json"))
now = datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc)
future = {e["contactId"] for e in ev if e.get("contactId") and e.get("startTime")
          and datetime.datetime.fromisoformat(e["startTime"]) > now
          and e.get("status") not in ("cancelled", "invalid")}
rows = [r for r in csv.DictReader(open("juan-call-list.csv"))
        if r["contact id"] not in dialled and r["contact id"] not in future]
tzmap = {}
for loc in ("sms", "email"):
    for line in open(f"contacts_{loc}.jsonl"):
        import json as j; ct = j.loads(line); tzmap[ct["id"]] = ct.get("timezone") or ""
with open("list-finish.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rank","priority","name","phone","email","why they're a fit","score","best time to call","sub-account","contact id","GHL link"])
    for i, r in enumerate(rows, 1):
        tz = tzmap.get(r["contact id"], "").split("/")[-1].replace("_", " ") or "unknown"
        w.writerow([i, r["priority"], r["name"], r["phone"], r["email"], r["why they're a fit"],
                    r["score"], f"noon-2pm {tz}", r["sub-account"], r["contact id"], r["GHL link"]])
print("still to dial from the 10/19 list:", len(rows))
import collections; print(collections.Counter(r["priority"] for r in rows))
