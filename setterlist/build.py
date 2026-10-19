"""Pick and rank setter-call targets from the SMS and EMAIL GHL sub-accounts."""
import json, sys, csv, datetime, collections
sys.path.insert(0, "/tmp/claude-0/-home-user-GHL-Claude/3b1f4415-bbb0-5383-a14e-619747f7ce96/scratchpad")
from rules import *

STAGES = {}            # stageId -> (pipelineName, stageName)
def load_stages():
    import os
    sys.path.insert(0, "/home/user/GHL-Claude")
    from ghl.client import GHLClient
    for tk, loc in [("GHL_SMS_API_KEY","GHL_SMS_LOCATION_ID"),("GHL_EMAIL_API_KEY","GHL_EMAIL_LOCATION_ID")]:
        c = GHLClient(os.environ[tk], os.environ[loc])
        for p in c.get("/opportunities/pipelines").get("pipelines", []):
            for s in p.get("stages", []):
                STAGES[s["id"]] = (p.get("name",""), (s.get("name") or "").strip().lower())

def jl(path):
    with open(path) as f:
        for line in f:
            yield json.loads(line)

def load():
    contacts = {}
    for loc in ("sms", "email"):
        for ct in jl(f"contacts_{loc}.jsonl"):
            ct["loc"] = loc
            contacts[(loc, ct["id"])] = ct
    convs = {}
    for loc in ("sms", "email"):
        for cv in jl(f"conv_{loc}.jsonl"):
            k = (loc, cv.get("contactId"))
            prev = convs.get(k)
            if not prev or (cv.get("lastMessageDate") or 0) > (prev.get("lastMessageDate") or 0):
                convs[k] = cv
    opps = collections.defaultdict(list)
    for loc in ("sms", "email"):
        for o in jl(f"opps_{loc}.jsonl"):
            opps[(loc, o.get("contactId"))].append(o)
    events = json.load(open("events.json"))
    return contacts, convs, opps, events

def dnd_blocked(ct):
    if ct.get("dnd"):
        return "global DND"
    for key in ("dndSettings", "inboundDndSettings"):
        s = (ct.get(key) or {})
        for ch in ("Call", "call", "SMS", "Phone"):
            v = s.get(ch)
            if isinstance(v, dict) and str(v.get("status","")).lower() == "active" and ch.lower() in ("call","phone"):
                return f"{ch} DND"
    tags = [t.lower() for t in (ct.get("tags") or [])]
    for t in NOCALL_TAGS:
        if t in tags:
            return f"tag '{t}'"
    return None

def owned(ct, oppslist):
    tags = [t.lower() for t in (ct.get("tags") or [])]
    for product, keys in OWNERSHIP.items():
        for k in keys:
            if k in tags:
                return f"{product} (tag '{k}')"
    for o in oppslist:
        pipe, stage = STAGES.get(o.get("pipelineStageId"), ("", ""))
        if o.get("status") == "won":
            return f"won opportunity in {pipe}"
        if stage in STAGE_OWNED:
            return f"pipeline stage '{stage}' in {pipe}"
        if pipe.lower() in ("bot support", "futures support", "flight path support"):
            return f"in {pipe} pipeline"
    return None

def future_appt(ct, oppslist, future_ids):
    if ct["id"] in future_ids:
        return "confirmed appointment on the calendar"
    for o in oppslist:
        pipe, stage = STAGES.get(o.get("pipelineStageId"), ("", ""))
        if o.get("status") == "open" and stage in STAGE_BOOKED:
            d = days_ago(o.get("lastStageChangeAt") or o.get("updatedAt"))
            if d is not None and d <= 45:
                return f"open opportunity sitting in '{stage}' ({d}d)"
    return None

def dead(ct, oppslist):
    tags = [t.lower() for t in (ct.get("tags") or [])]
    for t in DISQUALIFY_TAGS:
        if t in tags:
            return f"tag '{t}'"
    for o in oppslist:
        pipe, stage = STAGES.get(o.get("pipelineStageId"), ("", ""))
        if stage in STAGE_DEAD and o.get("status") in ("open", "lost", "abandoned"):
            return f"pipeline stage '{stage}'"
    return None

def profile(ct, cv, oppslist):
    """Engagement signals and the score built from them."""
    tags = [t.lower() for t in (ct.get("tags") or [])]
    p = {"score": 0, "why": [], "signals": {}}
    def add(points, note, key=None, val=None):
        p["score"] += points
        if note: p["why"].append(note)
        if key: p["signals"][key] = val

    # 1. brand new lead
    age = days_ago(ct.get("dateAdded"))
    p["signals"]["lead_age_days"] = age
    if age is not None:
        if age <= 3:    add(45, f"brand new lead ({age}d old)")
        elif age <= 7:  add(38, f"new lead ({age}d old)")
        elif age <= 14: add(30, f"new lead ({age}d old)")
        elif age <= 30: add(22, f"recent lead ({age}d old)")
        elif age <= 60: add(10, f"lead {age}d old")

    # 2. two-way conversation: they wrote or picked up
    lmd = (cv or {}).get("lastMessageDate")
    conv_days = None
    if lmd:
        conv_days = (TODAY - datetime.datetime.fromtimestamp(lmd/1000, datetime.timezone.utc)).days
    p["signals"]["last_msg_days"] = conv_days
    inbound = (cv or {}).get("lastMessageDirection") == "inbound"
    p["signals"]["last_msg_inbound"] = inbound
    if inbound and conv_days is not None:
        if conv_days <= 7:    add(40, f"replied to us {conv_days}d ago")
        elif conv_days <= 30: add(32, f"replied to us {conv_days}d ago")
        elif conv_days <= 90: add(20, f"replied to us {conv_days}d ago")
        else:                 add(8,  f"replied to us {conv_days}d ago")
    elif conv_days is not None and conv_days <= 30:
        add(6, f"in an active thread ({conv_days}d)")
    if (cv or {}).get("lastCallStatus") == "completed":
        cd = (cv or {}).get("lastCallTimestamp")
        if cd:
            d = (TODAY - datetime.datetime.fromtimestamp(cd/1000, datetime.timezone.utc)).days
            p["signals"]["last_call_days"] = d
            if d <= 90: add(6, f"answered a call {d}d ago")

    # 3. webinars
    best = None
    for t in tags:
        r = webinar_role(t)
        if r and (best is None or (r[1], r[2]) > (best[1], best[2])):
            best = r
    if best:
        word, weight, when = best
        wd = (TODAY - when).days
        p["signals"]["webinar"] = f"{when:%-m/%-d} {word} ({wd}d ago)"
        pts = {3: 34, 2: 24, 1: 12, 0: 2}[weight]
        if wd > 45:  pts = int(pts * 0.6)
        if wd > 120: pts = int(pts * 0.4)
        phrase = {"attended": "attended the {d} webinar", "attendee": "attended the {d} webinar",
                  "live": "attended the {d} webinar live", "showed": "showed for the {d} webinar",
                  "highly engaged": "watched most of the {d} webinar",
                  "replay": "watched the {d} replay", "watched replay": "watched the {d} replay",
                  "register": "registered for the {d} webinar but did not attend",
                  "registrant": "registered for the {d} webinar but did not attend",
                  "registered": "registered for the {d} webinar but did not attend",
                  "prospect": "came in off the {d} webinar"}.get(word, word + " the {d} webinar")
        if pts: add(pts, phrase.format(d=f"{when:%-m/%-d}"))

    # 4. clicks / opens
    clicks = [t for t in tags if any(w in t for w in CLICK_WORDS)]
    if clicks:
        p["signals"]["clicks"] = "; ".join(clicks[:3])
        add(12 if any("click" in c for c in clicks) else 5,
            "clicked a link in our email/SMS" if any("click" in c for c in clicks) else "opened our emails")

    # 5. explicit interest tags
    hot = [t for t in tags if t in REPLY_TAGS or t.startswith("warm")]
    if hot:
        p["signals"]["interest_tags"] = "; ".join(hot[:4])
        add(14, f"tagged {hot[0]}")

    # 6. live in an active pipeline stage
    for o in oppslist:
        pipe, stage = STAGES.get(o.get("pipelineStageId"), ("", ""))
        if o.get("status") == "open" and stage in STAGE_ACTIVE:
            d = days_ago(o.get("lastStageChangeAt") or o.get("updatedAt"))
            p["signals"]["pipeline"] = f"{pipe} / {stage} ({d}d)"
            if d is not None and d <= 30:   add(14, f"open in {pipe} at '{stage}'")
            elif d is not None and d <= 120: add(7, f"open in {pipe} at '{stage}'")
            break

    # 7. prior no-show / cancel: still worth calling, slightly less likely
    if any(t in tags for t in ("webinar-no-show", "rescheduled", "no show", "cancelled", "canceled")):
        add(-6, None)

    # 8. survey answers (prep call form) as a fit signal
    p["signals"]["survey"] = ""
    # 9. general recency of any activity
    la = days_ago(ct.get("lastActivity"))
    p["signals"]["last_activity_days"] = la
    if la is not None and la <= 14: add(8, None)
    elif la is not None and la <= 45: add(4, None)
    return p

def main():
    load_stages()
    contacts, convs, opps, events = load()
    nowi = datetime.datetime.now(datetime.timezone.utc)
    future_ids = {e["contactId"] for e in events
                  if e.get("contactId") and e.get("startTime")
                  and datetime.datetime.fromisoformat(e["startTime"]) > nowi
                  and e.get("status") not in ("cancelled", "invalid")}
    reasons = collections.Counter()
    kept = []
    for key, ct in contacts.items():
        loc = ct["loc"]; olist = opps.get((loc, ct["id"]), [])
        phone = callable_phone(ct.get("phone"))
        if not phone:
            reasons["no usable phone"] += 1; continue
        b = dnd_blocked(ct)
        if b: reasons["DND / not callable"] += 1; continue
        o = owned(ct, olist)
        if o: reasons["already owns a product"] += 1; continue
        f = future_appt(ct, olist, future_ids)
        if f: reasons["appointment already booked"] += 1; continue
        d = dead(ct, olist)
        if d: reasons["disqualified / bad fit"] += 1; continue
        em = (ct.get("email") or "").lower()
        if em.endswith("universityofoptions.com") or "test" in em.split("@")[0][:4]:
            reasons["internal / test record"] += 1; continue
        p = profile(ct, convs.get((loc, ct["id"])), olist)
        if p["score"] <= 0:
            reasons["no engagement signal"] += 1; continue
        ct["_phone"] = phone; ct["_p"] = p
        kept.append(ct)
    print("eligible:", len(kept))
    for k, v in reasons.most_common(): print(f"  excluded {v:7,d}  {k}")
    json.dump([{ "loc": c["loc"], "id": c["id"], "name": (c.get("contactName") or "").strip(),
                 "first": c.get("firstName"), "last": c.get("lastName"), "email": c.get("email"),
                 "phone": c["_phone"], "score": c["_p"]["score"], "why": c["_p"]["why"],
                 "signals": c["_p"]["signals"], "tags": c.get("tags"), "source": c.get("source"),
                 "dateAdded": c.get("dateAdded"), "customFields": c.get("customFields")}
               for c in sorted(kept, key=lambda c: -c["_p"]["score"])],
              open("eligible.json","w"), default=str)
    sc = sorted((c["_p"]["score"] for c in kept), reverse=True)
    print("top scores:", sc[:5], "| 250th:", sc[249] if len(sc)>249 else None, "| median:", sc[len(sc)//2])

if __name__ == "__main__":
    main()
