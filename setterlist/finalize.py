"""De-duplicate across the two accounts, pick 250, and write the call sheet."""
import json, csv, sys, collections, datetime
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
from rules import TODAY

CF = json.load(open("custom_fields.json"))
CAP_FIELDS = [k for k, v in CF.items() if "capital" in (v["name"] or "").lower()]
EXP_FIELDS = [k for k, v in CF.items()
              if any(w in (v["name"] or "").lower() for w in
                     ("how long have you been trading", "how experienced are you",
                      "how much trading experience", "what is your level of trade experience",
                      "what's your trading experience"))]
GOAL_FIELDS = [k for k, v in CF.items() if "main goal with trading" in (v["name"] or "").lower()]
OWN_FIELDS = [k for k, v in CF.items() if "currently own" in (v["name"] or "").lower()]

def cf_value(row, ids):
    for f in (row.get("customFields") or []):
        if f.get("id") in ids and f.get("value") not in (None, "", [], {}):
            v = f["value"]
            return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    return ""

rows = json.load(open("eligible.json"))

# --- drop anyone whose own survey answer says they already own one of the three ---
OWNED_WORDS = ("options navigator", "options bot", "futures", "flight school", "navigator")
pre = len(rows)
rows = [r for r in rows if not any(w in cf_value(r, OWN_FIELDS).lower() for w in OWNED_WORDS)]
print("dropped by survey 'programs you currently own':", pre - len(rows))

# --- de-duplicate the same human across the two sub-accounts -------------------
def keys(r):
    out = []
    if r.get("email"): out.append(("e", r["email"].strip().lower()))
    if r.get("phone"): out.append(("p", r["phone"]))
    return out

best = {}
order = []
for r in sorted(rows, key=lambda r: (-r["score"], r["loc"] != "sms")):
    hit = None
    for k in keys(r):
        if k in best:
            hit = best[k]; break
    if hit is None:
        r["also_in"] = []
        order.append(r)
        for k in keys(r): best[k] = r
    else:
        # same person, second account: keep the higher-scoring record, remember the other
        hit.setdefault("also_in", []).append(r["loc"])
        hit["score"] = max(hit["score"], r["score"])
        for w in r["why"]:
            if w not in hit["why"]: hit["why"].append(w)
        if hit["loc"] != "sms" and r["loc"] == "sms":
            # prefer the SMS record as the one Juan and the tag live on
            r["also_in"] = [hit["loc"]] + hit.get("also_in", [])
            r["why"] = hit["why"]; r["score"] = hit["score"]
            idx = order.index(hit); order[idx] = r
            for k in keys(r) + keys(hit): best[k] = r
        else:
            for k in keys(r): best[k] = r
print("unique people:", len(order), "| cross-account:", sum(1 for r in order if r.get("also_in")))

TARGET = 250
NEW_SLOTS = 60          # reserved for leads that came in this month, as Audry asked for "very new"
by_score = sorted(order, key=lambda r: -r["score"])
picked, seen = [], set()
for r in by_score[:TARGET - NEW_SLOTS]:
    picked.append(r); seen.add(id(r))
newest = [r for r in by_score if id(r) not in seen
          and (r["signals"].get("lead_age_days") is not None and r["signals"]["lead_age_days"] <= 30)]
newest.sort(key=lambda r: (r["signals"]["lead_age_days"], -r["score"]))
for r in newest:
    if len(picked) >= TARGET: break
    picked.append(r); seen.add(id(r))
for r in by_score:                      # top up if there were not enough new leads
    if len(picked) >= TARGET: break
    if id(r) not in seen: picked.append(r); seen.add(id(r))
picked.sort(key=lambda r: -r["score"])

def why_text(r):
    bits = list(r["why"])
    cap = cf_value(r, CAP_FIELDS); exp = cf_value(r, EXP_FIELDS); goal = cf_value(r, GOAL_FIELDS)
    if cap: bits.append(f"says they have {cap} to trade with")
    if exp: bits.append(f"experience: {exp}")
    if goal: bits.append(f"goal: {goal}")
    return "; ".join(b for b in bits if b).capitalize()

def band(s):
    return "A - call first" if s >= 70 else ("B - strong" if s >= 55 else "C - worth a dial")

with open("juan-call-list.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["rank","priority","name","phone","email","why they're a fit","score",
                "lead age (days)","last reply (days)","last webinar","clicked/opened",
                "pipeline","capital","experience","sub-account","also in","contact id","GHL link"])
    for i, r in enumerate(picked, 1):
        sg = r["signals"]
        loc = "SMS" if r["loc"] == "sms" else "Main/Email"
        locid = "U23Jnu7rscfzAOUmSevW" if r["loc"] == "sms" else "IyorbIIbJLsMLaqy8j1P"
        w.writerow([i, band(r["score"]), (r["name"] or "").title(), r["phone"], r.get("email") or "",
                    why_text(r), r["score"], sg.get("lead_age_days"),
                    sg.get("last_msg_days") if sg.get("last_msg_inbound") else "",
                    sg.get("webinar",""), sg.get("clicks",""), sg.get("pipeline",""),
                    cf_value(r, CAP_FIELDS), cf_value(r, EXP_FIELDS), loc,
                    ", ".join("Main/Email" if x=="email" else "SMS" for x in r.get("also_in") or []),
                    r["id"], f"https://app.gohighlevel.com/v2/location/{locid}/contacts/detail/{r['id']}"])
json.dump([{"id": r["id"], "loc": r["loc"], "name": r["name"], "score": r["score"]} for r in picked],
          open("picked.json","w"))
print("wrote juan-call-list.csv:", len(picked))
print("score range:", picked[0]["score"], "->", picked[-1]["score"])
print("bands:", collections.Counter(band(r["score"]) for r in picked))
print("sub-account:", collections.Counter(r["loc"] for r in picked))
ages = [r["signals"].get("lead_age_days") for r in picked]
print("lead age <=7d:", sum(1 for a in ages if a is not None and a<=7),
      "| <=30d:", sum(1 for a in ages if a is not None and a<=30))
print("replied in last 30d:", sum(1 for r in picked if r["signals"].get("last_msg_inbound") and (r["signals"].get("last_msg_days") or 999)<=30))
