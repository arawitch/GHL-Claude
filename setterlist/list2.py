"""Build the next call lists for Juan, ordered by what actually worked in week one."""
import json, sys, csv, datetime, collections
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
import rules
TODAY_NOW = datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc)
rules.TODAY = TODAY_NOW                      # the dumps are from today, not from the 19th
import build
from rules import webinar_role, days_ago, callable_phone
build.load_stages()
contacts, convs, opps, events = build.load()
nowi = TODAY_NOW
future_ids = {e["contactId"] for e in events
              if e.get("contactId") and e.get("startTime")
              and datetime.datetime.fromisoformat(e["startTime"]) > nowi
              and e.get("status") not in ("cancelled", "invalid")}
past_noshow = {e["contactId"] for e in events if e.get("status") == "noshow"}
CF = json.load(open("custom_fields.json"))
CAP = [k for k, v in CF.items() if "capital" in (v["name"] or "").lower()]

already = {r["contact id"] for r in csv.DictReader(open("juan-call-list.csv"))}
week1 = json.load(open("week1.json"))
already |= set(week1["dialled"])

def cap_answer(ct):
    for f in (ct.get("customFields") or []):
        if f.get("id") in CAP and f.get("value"):
            v = f["value"]
            if isinstance(v, list): v = ", ".join(str(x) for x in v)
            v = str(v).strip().strip("[]'\"")
            if v.lower().startswith("yes, i have at least"): return "at least $5k"
            if v.lower().startswith("no"): return "under $5k"
            return v
    return ""

def webinar_best(ct):
    best = None
    for t in (ct.get("tags") or []):
        r = webinar_role(t.lower())
        if r and (best is None or (r[1], r[2]) > (best[1], best[2])): best = r
    return best

def score(ct, cv):
    tags = [t.lower() for t in (ct.get("tags") or [])]
    pts, why = 0, []
    age = days_ago(ct.get("dateAdded"))
    age = max(0, age) if age is not None else None
    if age is not None:
        if age <= 3:    pts += 48; why.append(f"brand new lead, {age} days old")
        elif age <= 7:  pts += 45; why.append(f"new lead, {age} days old")
        elif age <= 30: pts += 35; why.append(f"came in {age} days ago")
        elif age <= 90: pts += 12; why.append(f"{age} days in the CRM")
    w = webinar_best(ct)
    if w:
        word, weight, when = w
        if weight == 3:
            pts += 30; why.append(f"attended the {when:%-m/%-d} webinar live, and live attendees keep 75% of their appointments")
        elif weight == 2:
            pts += 8; why.append(f"watched the {when:%-m/%-d} replay")
        else:
            pts += 4; why.append(f"registered for the {when:%-m/%-d} webinar")
    if "weekly newsletter subscriber" in tags:
        pts += 20; why.append("newsletter subscriber, and they show up to 72% of their appointments")
    if "tier 1" in tags:
        pts += 15; why.append("tier 1")
    if any("clicked webinar invite" in t or "clicked" in t and "invite" in t for t in tags):
        pts += 15; why.append("clicked a webinar invite")
    cap = cap_answer(ct)
    if cap:
        pts += 10; why.append(f"says they have {cap} to trade with")
        if any(k in cap.lower() for k in ("10,000", "$10k", "more than", "25,000", "50,000")): pts += 5
    lmd = (cv or {}).get("lastMessageDate")
    if lmd and (cv or {}).get("lastMessageDirection") == "inbound":
        d = (TODAY_NOW - datetime.datetime.fromtimestamp(lmd/1000, datetime.timezone.utc)).days
        if d <= 14: pts += 10; why.append(f"texted us back {d} days ago")
    if ct["id"] in past_noshow or "webinar-no-show" in tags or "no show" in tags:
        pts -= 25; why.append("has missed an appointment before, so confirm the time twice")
    return pts, why

SKIP_TAGS = ("2. ltn [long term nurture]", "disqualify", "ltn")
eligible = []
for (loc, cid), ct in contacts.items():
    if cid in already or cid in future_ids: continue
    tags = [t.lower() for t in (ct.get("tags") or [])]
    if any(t in tags for t in SKIP_TAGS): continue
    phone = callable_phone(ct.get("phone"))
    if not phone: continue
    olist = opps.get((loc, cid), [])
    if build.dnd_blocked(ct) or build.owned(ct, olist) or build.dead(ct, olist): continue
    if build.future_appt(ct, olist, future_ids): continue
    em = (ct.get("email") or "").lower()
    if em.endswith("universityofoptions.com"): continue
    pts, why = score(ct, convs.get((loc, cid)))
    age = max(0, days_ago(ct.get("dateAdded")) or 0)
    w = webinar_best(ct)
    eligible.append({"loc": loc, "id": cid, "name": (ct.get("contactName") or "").strip(),
                     "email": ct.get("email"), "phone": phone, "score": pts, "why": why,
                     "age": age, "webinar": f"{w[2]:%-m/%-d} {w[0]}" if w else "",
                     "live": bool(w and w[1] == 3), "news": "weekly newsletter subscriber" in tags,
                     "cap": cap_answer(ct), "tz": ct.get("timezone") or "",
                     "noshow": cid in past_noshow})
print("eligible pool, nobody called yet:", len(eligible))

# de-duplicate the same person across the two accounts, keeping the SMS record
seen, uniq = {}, []
for r in sorted(eligible, key=lambda r: (-r["score"], r["loc"] != "sms")):
    k = (r.get("email") or "").strip().lower() or r["phone"]
    k2 = r["phone"]
    if k in seen or k2 in seen: continue
    seen[k] = seen[k2] = r; uniq.append(r)
print("unique people:", len(uniq))

def sheet(rows, path, title):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank","name","phone","email","why they're a fit","score","lead age (days)",
                    "webinar","capital","best time to call","missed one before","sub-account","contact id","GHL link"])
        for i, r in enumerate(rows, 1):
            tz = r["tz"].split("/")[-1].replace("_", " ") if r["tz"] else "unknown"
            locid = "U23Jnu7rscfzAOUmSevW" if r["loc"] == "sms" else "IyorbIIbJLsMLaqy8j1P"
            w.writerow([i, (r["name"] or "").title(), r["phone"], r["email"] or "",
                        "; ".join(r["why"]).capitalize(), r["score"], r["age"], r["webinar"], r["cap"],
                        f"noon-2pm {tz}", "yes" if r["noshow"] else "", 
                        "SMS" if r["loc"]=="sms" else "Main/Email", r["id"],
                        f"https://app.gohighlevel.com/v2/location/{locid}/contacts/detail/{r['id']}"])
    print(f"{title}: {len(rows)} -> {path}")

fresh = [r for r in uniq if r["age"] is not None and r["age"] <= 60]
fresh.sort(key=lambda r: (r["age"], -r["score"]))
fresh = fresh[:250]
print("fresh pool by age band:", collections.Counter(
    "0-7d" if r["age"]<=7 else ("8-30d" if r["age"]<=30 else "31-60d") for r in fresh))

freshids = {r["id"] for r in fresh}
showup = [r for r in uniq if (r["live"] or r["news"]) and not r["noshow"] and r["id"] not in freshids]
showup.sort(key=lambda r: -r["score"])
showup = showup[:250]

sheet(fresh, "list-fresh.csv", "List 1, newest leads")
showup_sms = [r for r in showup if r["loc"] == "sms"]
showup_main = [r for r in showup if r["loc"] != "sms"]
sheet(showup_sms, "list-showup.csv", "List 2, best show-up profile (SMS account)")
sheet(showup_main, "list-showup-main.csv", "Same profile but main account only")
json.dump({"fresh": [{"id": r["id"], "loc": r["loc"], "name": r["name"]} for r in fresh],
           "showup": [{"id": r["id"], "loc": r["loc"], "name": r["name"]} for r in showup_sms],
           "showup_main": [{"id": r["id"], "loc": r["loc"], "name": r["name"]} for r in showup_main]},
          open("new_lists.json", "w"))
print("\nfresh list: ages", collections.Counter(r["age"] for r in fresh[:5]), "... oldest", fresh[-1]["age"] if fresh else None)
print("showup list: live attendees", sum(r["live"] for r in showup), "| newsletter", sum(r["news"] for r in showup))
