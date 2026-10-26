"""Juan's week on the list: who answered, who booked, who showed, and what they have in common."""
import json, sys, csv, datetime, collections
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
from rules import webinar_role
JUAN, DARREN, JOEL = "xxcp9j8UStACv8KfYRjj", "N4SovNONFMNkrLs3JpT1", "vfRCYHRUq6e6xsJfaaud"
HAND = "2026-10-19T15:00:00Z"

act = json.load(open("call_activity.json"))
sheet = {r["contact id"]: r for r in csv.DictReader(open("juan-call-list.csv"))}
contacts = {}
for loc in ("sms", "email"):
    for line in open(f"contacts_{loc}.jsonl"):
        ct = json.loads(line); contacts[ct["id"]] = ct
CF = json.load(open("custom_fields.json"))
CAP = [k for k, v in CF.items() if "capital" in (v["name"] or "").lower()]
ev = json.load(open("events.json"))

def cap_band(ct):
    for f in (ct.get("customFields") or []):
        if f.get("id") in CAP and f.get("value"):
            v = str(f["value"]).lower()
            if "less than $5" in v or "$1k-$4k" in v: return "under $5k"
            if "5,000-$9" in v or "5,000–$9" in v or "$5k-$9k" in v: return "$5-10k"
            if "unsure" in v or "don't want" in v: return "would not say"
            return "$10k+"
    return "no answer"

def webinar_state(ct):
    best = None
    for t in (ct.get("tags") or []):
        r = webinar_role(t.lower())
        if r and (best is None or (r[1], r[2]) > (best[1], best[2])): best = r
    if not best: return "no webinar"
    return {3: "attended live", 2: "watched replay", 1: "registered only", 0: "registered only"}[best[1]]

# ---- Juan's dialling ---------------------------------------------------------
dials = collections.defaultdict(list)
for cid, v in act.items():
    for c in v.get("calls", []):
        if c.get("user") == JUAN: dials[cid].append(c)
print("Juan: contacts dialled", len(dials), "| call records", sum(len(v) for v in dials.values()))
byday = collections.Counter(c["when"][:10] for v in dials.values() for c in v)
print("by day:", dict(sorted(byday.items())))

def connected(calls): return max((int(c["dur"] or 0) for c in calls), default=0) >= 30
picked = {cid for cid, v in dials.items() if connected(v)}
print(f"answered (30s+): {len(picked)} of {len(dials)} dialled = {100*len(picked)/len(dials):.0f}%")

# dial hour, in the contact's own timezone where we know it
def local_hour(when, ct):
    t = datetime.datetime.fromisoformat(when.replace("Z", "+00:00"))
    tz = (ct or {}).get("timezone") or ""
    off = {"America/New_York": -4, "America/Detroit": -4, "America/Toronto": -4,
           "America/Chicago": -5, "America/Denver": -6, "America/Phoenix": -7,
           "America/Los_Angeles": -7, "America/Anchorage": -8, "Pacific/Honolulu": -10}.get(tz)
    if off is None: off = -5
    return (t + datetime.timedelta(hours=off)).hour

hourstat = collections.defaultdict(lambda: [0, 0])
for cid, v in dials.items():
    h = local_hour(v[0]["when"], contacts.get(cid))
    hourstat[h][0] += 1
    hourstat[h][1] += (cid in picked)
print("\npickup rate by the contact's own local hour (first dial):")
for h in sorted(hourstat):
    n, s = hourstat[h]
    print(f"   {h:02d}:00  {s:2d}/{n:3d} answered  {100*s/n:5.0f}%" + ("" if n >= 8 else "   (thin)"))

def compare(name, fn):
    g = collections.defaultdict(lambda: [0, 0])
    for cid in dials:
        k = fn(contacts.get(cid) or {}, sheet.get(cid) or {})
        g[k][0] += 1; g[k][1] += (cid in picked)
    print(f"\n{name}:")
    for k, (n, s) in sorted(g.items(), key=lambda kv: -kv[1][1]/max(kv[1][0], 1)):
        print(f"   {str(k)[:32]:32s} {s:2d}/{n:3d} answered  {100*s/n:5.0f}%" + ("" if n >= 8 else "   (thin)"))

compare("Pickup by webinar history", lambda ct, r: webinar_state(ct))
compare("Pickup by capital they stated", lambda ct, r: cap_band(ct))
compare("Pickup by priority band on my sheet", lambda ct, r: r.get("priority", "?"))
def age_band(ct, r):
    a = r.get("lead age (days)")
    a = int(a) if str(a).isdigit() else None
    if a is None: return "unknown"
    return "0-7 days old" if a <= 7 else ("8-30 days" if a <= 30 else ("1-6 months" if a <= 180 else "over 6 months"))
compare("Pickup by how new the lead is", age_band)
compare("Pickup by whether they had replied to us before",
        lambda ct, r: "had replied to us" if r.get("last reply (days)") else "never replied")

# ---- bookings and shows off the list ---------------------------------------
listed = set(sheet)
booked = []
for e in ev:
    if e.get("contactId") in listed and str(e.get("startTime") or "") >= "2026-10-19":
        booked.append(e)
print("\nappointments for list members since the handover:", len(booked))
for b in sorted(booked, key=lambda x: str(x["startTime"])):
    cid = b["contactId"]; r = sheet.get(cid, {})
    print(f"   rank {r.get('rank','?'):>3} {r.get('name','?')[:22]:22s} {b['status']:9s} {str(b['startTime'])[:16]}  "
          f"{'ANSWERED Juan' if cid in picked else ('dialled' if cid in dials else 'no Juan call')}  "
          f"| {webinar_state(contacts.get(cid) or {})}")
shows = [b for b in booked if b["status"] == "showed"]
nos = [b for b in booked if b["status"] == "noshow"]
print(f"outcome so far: {len(shows)} showed, {len(nos)} no-showed, "
      f"{sum(1 for b in booked if b['status']=='confirmed')} still upcoming, "
      f"{sum(1 for b in booked if b['status']=='cancelled')} cancelled")
json.dump({"picked": sorted(picked), "dialled": sorted(dials),
           "booked": [{"id": b["contactId"], "status": b["status"], "start": str(b["startTime"])} for b in booked]},
          open("week1.json", "w"))
