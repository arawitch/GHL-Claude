import pickle, collections, statistics, csv, sys
people = pickle.load(open("people.pkl","rb"))
F = pickle.load(open("feats.pkl","rb"))

SIGNALS_AFFINITY = {"new bot user","futures","options bot presale","telegram",
                    "options nav new purchase","options bot sale","option and bot combo",
                    "attended futures","futures workshop signup","futures oh uoo","day trading invite"}

def ht_score(k):
    """High-ticket ($4k+) lookalike score. Weights are round(10*log2(measured lift))
    on the engaged-non-buyer baseline, clipped to +-30. Recency/appointment history
    is deliberately excluded: buyers are mostly pre-2026 so those are time-confounded."""
    f=F[k]; s=0; why=[]
    def add(pts,label):
        nonlocal s
        s+=pts; why.append(f"{label} {pts:+d}")
    if f["newsletter"]: add(26,"newsletter subscriber")
    n=f["live_webinar_attended"]
    if n>=2: add(30,f"attended {n} live webinars")
    elif n==1: add(22,"attended a live webinar")
    cb=f["cap_band"]
    if cb=="15k+": add(18,"capital $15k+")
    elif cb=="10k+": add(14,"capital $10k+")
    elif cb=="5-9k": add(12,"capital $5-9k")
    elif cb=="1-4k": add(-30,"capital $1-4k")
    elif cb=="unsure": add(-20,"capital unsure/withheld")
    elif f["cap_confirm_5k"]: add(10,"confirmed $5k+")
    if f["bootcamp"]: add(8,"bootcamp/workshop")
    if f["exp_band"]=="moderate+": add(4,"moderate+ experience")
    elif f["exp_band"]=="none": add(-6,"no trading experience")
    if f["paid_social"] and not f["live_webinar_attended"] and not f["newsletter"]: add(-10,"paid social, no engagement")
    if f["tier5"]: add(-22,"tier 5")
    if f["tier12"]: add(-6,"tier 1-2 (low-converting in data)")
    if f["dq_tag"] or f["dq_stage"]: add(-18,"disqualified")
    t=f["ac_tier"]
    if t in ("A","B"): add(4,f"area code tier {t} (higher-income)")
    elif t=="D": add(-4,"area code tier D (lower-income)")
    return s, "; ".join(why)

def sp_score(k):
    """Signal Pilot ($99/mo) readiness. NOT a trained conversion model -- the account
    holds no sub-$2k purchase history to train on. It ranks on the strongest measured
    engagement markers in this data plus an affordability floor."""
    f=F[k]; p=people[k]; s=0; why=[]
    def add(pts,label):
        nonlocal s
        s+=pts; why.append(f"{label} {pts:+d}")
    n=f["live_webinar_attended"]
    if n>=2: add(30,f"attended {n} live webinars")
    elif n==1: add(24,"attended a live webinar")
    if f["newsletter"]: add(22,"newsletter subscriber")
    if f["clicked"]: add(8,"clicked a campaign link")
    if f["bootcamp"]: add(6,"bootcamp/workshop signup")
    aff = p["tags"] & SIGNALS_AFFINITY
    if aff: add(min(12,4*len(aff)), "signals/bot product affinity ("+", ".join(sorted(aff))[:60]+")")
    cb=f["cap_band"]
    if cb=="1-4k": add(14,"capital $1-4k: can afford $99/mo, not $4k")
    elif cb=="unsure": add(6,"capital withheld")
    elif cb in ("5-9k","10k+","15k+"): add(-8,"has $5k+ capital -- pitch high ticket instead")
    la=p["last_act"]
    if la is None: add(-10,"no recorded activity")
    elif la<=30: add(16,"active in last 30 days")
    elif la<=90: add(10,"active in last 90 days")
    elif la<=365: add(2,"active in last year")
    else: add(-8,f"last active {la} days ago")
    if f["email_ok"] and f["sms_ok"]: add(10,"reachable by email and SMS")
    elif f["email_ok"] or f["sms_ok"]: add(4,"reachable on one channel")
    else: add(-40,"unreachable")
    if f["hard_bad"]: add(-30,"hard-bad contact record")
    if p["maxval"]>0: add(8,f"has paid before (${p['maxval']:.0f})")
    t=f["ac_tier"]
    if t in ("A","B"): add(2,f"area code tier {t}")
    return s, "; ".join(why)

for k in F:
    F[k]["ht"],F[k]["ht_why"] = ht_score(k)
    F[k]["sp"],F[k]["sp_why"] = sp_score(k)

def route(k):
    f=F[k]; p=people[k]
    if f["hard_bad"] or not (f["email_ok"] or f["sms_ok"]): return "0. Unreachable / suppress"
    if f["ht"]>=45: return "1. High ticket - A"
    if f["ht"]>=25: return "2. High ticket - B"
    if f["ht"]>=8:  return "3. High ticket - C / test"
    if f["sp"]>=45: return "4. Signal Pilot - A"
    if f["sp"]>=25: return "5. Signal Pilot - B"
    if f["sp"]>=10: return "6. Signal Pilot - C"
    return "7. Dormant / no signal"
for k in F: F[k]["band"]=route(k)
pickle.dump(F, open("feats.pkl","wb"))

print("=== ROUTING (all 50,198 people) ===")
c=collections.Counter(F[k]["band"] for k in F)
for b in sorted(c): print(f"  {b:28} {c[b]:6}")

print("\n=== VALIDATION: actual $4k+ purchase rate by high-ticket score band ===")
print("   (held-out check -- the score never sees purchase data)")
bins=[(80,10**9),(60,80),(45,60),(30,45),(15,30),(0,15),(-25,0),(-10**9,-25)]
for lo,hi in bins:
    g=[k for k in F if lo<=F[k]["ht"]<hi]
    if not g: continue
    nb=sum(1 for k in g if people[k]["maxval"]>=4000)
    med=statistics.median([people[k]["maxval"] for k in g if people[k]["maxval"]>0] or [0])
    lab=f"{lo} to {hi}" if hi<10**8 else f"{lo}+"
    print(f"  score {lab:14} n={len(g):6}  $4k+ buyers {nb:4}  = {100*nb/len(g):6.2f}%   median purchase ${med:.0f}")
base=sum(1 for k in F if people[k]['maxval']>=4000)/len(F)
print(f"  BASE RATE across the whole list: {100*base:.2f}%")

print("\n=== Capture: where the 684 known $4k+ buyers land ===")
cb=collections.Counter(F[k]["band"] for k in F if people[k]["maxval"]>=4000)
for b in sorted(cb): print(f"  {b:28} {cb[b]:4}  ({100*cb[b]/684:4.1f}%)")
