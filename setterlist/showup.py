"""What separates a kept appointment from a no-show, across every appointment in both accounts."""
import json, sys, datetime, collections, math
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
from rules import webinar_role, days_ago

ev = json.load(open("events.json"))
contacts = {}
for loc in ("sms", "email"):
    for line in open(f"contacts_{loc}.jsonl"):
        ct = json.loads(line)
        contacts[(loc, ct["id"])] = ct
CF = json.load(open("custom_fields.json"))
CAP = [k for k, v in CF.items() if "capital" in (v["name"] or "").lower()]

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
    return {3: "attended live", 2: "watched replay", 1: "registered, no-show", 0: "registered, no-show"}[best[1]]

def source_band(ct):
    s = (ct.get("source") or "").lower()
    if "prep call" in s or "survey" in s: return "survey / prep call form"
    if "import" in s or "csv" in s: return "house list import"
    if "webinar" in s or "replay" in s: return "webinar funnel"
    if not s: return "unknown"
    return s[:28]

rows = []
for e in ev:
    st = str(e.get("startTime") or "")
    status = e.get("status")
    if status not in ("showed", "noshow"): continue
    ct = contacts.get((e["loc"], e.get("contactId")))
    if not ct: continue
    try: start = datetime.datetime.fromisoformat(st)
    except ValueError: continue
    rows.append({"showed": status == "showed", "cal": e.get("cal"), "loc": e["loc"],
                 "weekday": start.strftime("%A"), "hour": start.hour,
                 "webinar": webinar_state(ct), "capital": cap_band(ct),
                 "source": source_band(ct), "contact": e.get("contactId"),
                 "tags": [t.lower() for t in (ct.get("tags") or [])]})
print("appointments with a show/no-show outcome:", len(rows),
      "| showed:", sum(r["showed"] for r in rows),
      f"({100*sum(r['showed'] for r in rows)/len(rows):.0f}%)")

def breakdown(field, label=None, minimum=15):
    g = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        g[r[field]][0] += 1; g[r[field]][1] += r["showed"]
    print(f"\n{label or field}:")
    for k, (n, s) in sorted(g.items(), key=lambda kv: -kv[1][1]/max(kv[1][0],1)):
        if n < minimum: continue
        print(f"   {str(k)[:34]:34s} {s:4d}/{n:4d} showed   {100*s/n:5.1f}%")

breakdown("webinar", "By webinar history")
breakdown("capital", "By the capital they told us they have")
breakdown("source", "By where the contact came from")
breakdown("weekday", "By day of the appointment")
breakdown("hour", "By hour of the appointment (local to the calendar)", minimum=25)

# which tags shift the show rate, over a decent base
base = sum(r["showed"] for r in rows) / len(rows)
tagstat = collections.defaultdict(lambda: [0, 0])
for r in rows:
    for t in set(r["tags"]):
        tagstat[t][0] += 1; tagstat[t][1] += r["showed"]
cand = [(t, n, s, s/n) for t, (n, s) in tagstat.items() if n >= 40]
print(f"\nBase show rate {100*base:.0f}%. Tags on 40+ appointments, best and worst:")
for t, n, s, rate in sorted(cand, key=lambda x: -x[3])[:12]:
    print(f"   +  {t[:40]:40s} {s:4d}/{n:4d}  {100*rate:5.1f}%")
print("   ---")
for t, n, s, rate in sorted(cand, key=lambda x: x[3])[:10]:
    print(f"   -  {t[:40]:40s} {s:4d}/{n:4d}  {100*rate:5.1f}%")
json.dump(rows, open("showup_rows.json", "w"))
