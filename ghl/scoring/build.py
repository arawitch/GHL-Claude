import json, collections, re, pickle, datetime, statistics

NOW = datetime.datetime(2026,10,30,tzinfo=datetime.timezone.utc)

# ---- field definitions ----
fieldname = {}
for L in ("SMS","EMAIL"):
    for f in json.load(open(f"cf_{L}.json")):
        fieldname[f["id"]] = (f["name"], f["dataType"])

# ---- pipeline/stage names ----
stagename = {}; pipename = {}
for L in ("SMS","EMAIL"):
    for p in json.load(open(f"pipes_{L}.json")):
        pipename[p["id"]] = p["name"]
        for s in p.get("stages",[]):
            stagename[s["id"]] = s["name"]

PURCHASE_STAGES = {"6. closed","5. closed","won","completed purchase","purchased",
                   "pay link sent","verbal agreement to purchase","verbal agreement to purchase",
                   "in the trading room","in trading room"}
HARD_PURCHASE = {"6. closed","5. closed","won","completed purchase","purchased"}
DQ_STAGES = {"disqualified","unqualified","bad lead","not ready yet","bad timing/maybe later",
             "price check zone","survey not submitted","no/bad number","invalid contact","lost"}

def days(s):
    if not s: return None
    try:
        d = datetime.datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: return None
    return (NOW-d).days

# ---- opportunities by contact ----
opps = collections.defaultdict(list)
for L in ("SMS","EMAIL"):
    for line in open(f"opps_{L}.jsonl"):
        o = json.loads(line)
        cid = o.get("contactId")
        if not cid: continue
        stg = (stagename.get(o.get("pipelineStageId"),"") or "").strip().lower()
        opps[cid].append(dict(
            acct=L, status=o.get("status"), value=float(o.get("monetaryValue") or 0),
            stage=stg, pipe=pipename.get(o.get("pipelineId"),""),
            source=o.get("source") or "",
            changed=days(o.get("lastStatusChangeAt") or o.get("updatedAt")),
            created=days(o.get("createdAt")),
        ))

# ---- contacts, deduped by email then phone ----
people = {}
def key(c):
    e = (c.get("email") or "").strip().lower()
    if e: return "e:"+e
    p = (c.get("phone") or "").strip()
    if p: return "p:"+p
    return "i:"+c["id"]

for L in ("SMS","EMAIL"):
    for line in open(f"contacts_{L}.jsonl"):
        c = json.loads(line)
        k = key(c)
        p = people.setdefault(k, dict(key=k, accts=set(), ids={}, tags=set(), cf={},
                                      email="", phone="", first="", last="",
                                      dnd=False, dndch=set(), added=None, last_act=None,
                                      attrib=set(), opps=[]))
        p["accts"].add(L); p["ids"][L] = c["id"]
        p["tags"] |= {t.strip().lower() for t in (c.get("tags") or []) if t and t.strip()}
        p["email"] = p["email"] or (c.get("email") or "").strip().lower()
        p["phone"] = p["phone"] or (c.get("phone") or "").strip()
        p["first"] = p["first"] or (c.get("firstName") or "")
        p["last"]  = p["last"]  or (c.get("lastName") or "")
        if c.get("dnd"): p["dnd"]=True
        for ch,st in (c.get("dndSettings") or {}).items():
            if isinstance(st,dict) and st.get("status")=="active": p["dndch"].add(ch.lower())
        a = days(c.get("dateAdded"))
        if a is not None: p["added"] = a if p["added"] is None else max(p["added"],a)
        la = days(c.get("lastActivity"))
        if la is not None: p["last_act"] = la if p["last_act"] is None else min(p["last_act"],la)
        att = c.get("attributionSource") or {}
        for kk in ("sessionSource","medium","utmSource"):
            v = att.get(kk)
            if v: p["attrib"].add(str(v).strip().lower())
        for f in (c.get("customFields") or []):
            fid = f.get("id"); val = f.get("value")
            if fid is None or val in (None,"",[],{}): continue
            nm = fieldname.get(fid,(fid,"TEXT"))[0]
            if isinstance(val,list): val = "; ".join(str(x) for x in val)
            p["cf"].setdefault(nm, str(val)[:400])
        for o in opps.get(c["id"],[]):
            p["opps"].append(o)

print("unique people:", len(people))
print("in both accounts:", sum(1 for p in people.values() if len(p["accts"])==2))
print("with any customFields:", sum(1 for p in people.values() if p["cf"]))
print("with any opportunity:", sum(1 for p in people.values() if p["opps"]))

# ---- purchase / dq classification ----
for p in people.values():
    pv = [o for o in p["opps"] if o["stage"] in PURCHASE_STAGES or o["status"]=="won"]
    hp = [o for o in p["opps"] if o["stage"] in HARD_PURCHASE or o["status"]=="won"]
    p["bought"] = bool(hp)
    p["bought_soft"] = bool(pv)
    p["maxval"] = max([o["value"] for o in pv], default=0.0)
    p["maxval_any"] = max([o["value"] for o in p["opps"]], default=0.0)
    p["dq"] = (not p["bought_soft"]) and any(o["stage"] in DQ_STAGES for o in p["opps"])
    p["dq_stages"] = sorted({o["stage"] for o in p["opps"] if o["stage"] in DQ_STAGES})
    p["purch_days"] = min([o["changed"] for o in hp if o["changed"] is not None], default=None)
    p["took_call"] = any(o["stage"] in ("3. showed","showed","showed ","meeting took place",
                                        "completed meeting with dan","review call completed") for o in p["opps"])
    p["booked"] = any("appoint" in o["stage"] or "booked" in o["stage"] or o["stage"] in ("scheduled","2. booked appointment","scheduled meeting with closer") for o in p["opps"])

pickle.dump(people, open("people.pkl","wb"))

b4 = [p for p in people.values() if p["maxval"]>=4000]
print("\n$4k+ buyers (purchase stage/won, value>=4000):", len(b4))
print("any purchase evidence (hard):", sum(1 for p in people.values() if p["bought"]))
vals=sorted(p["maxval"] for p in people.values() if p["maxval"]>0)
print("purchasers with a nonzero value:", len(vals))
import bisect
for t in (99,500,1000,2000,3000,4000,5000,7000,10000):
    print(f"  >= ${t}: {sum(1 for v in vals if v>=t)}")
print("disqualified (dq stage, no purchase):", sum(1 for p in people.values() if p["dq"]))
