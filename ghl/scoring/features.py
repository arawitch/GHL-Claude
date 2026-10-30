import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pickle, re, sys, collections
sys.path.insert(0,'.'); import areacodes as A
people = pickle.load(open("people.pkl","rb")); P=list(people.values())

ATTENDED = re.compile(r"(^|[\s/-])(attended|attendee|live)([\s/-]|$)|attended")
ABSENT   = re.compile(r"absent|no[- ]show|replay|register|invite|prospect")
MEMBER_EVENT = re.compile(r"flight path|futures oh vtf|bot check|ready for install")

CAP_Q   = "How much capital do you currently have in your trading account"
CAP_Q2  = "Approximately how much capital do you have available"
CAP_Q3  = "Our investing strategies requires initial capital"
EXP_Q   = "How Much Trading Experience Do you Have"
INC_Q   = "What is your primary source of income"
EMP_Q   = "Are you currently employed"
OCC_Q   = "What is your current occupation"
HHI_Q   = "What is your yearly household income"

def cfget(p, prefix):
    for k,v in p["cf"].items():
        if k.startswith(prefix[:45]): return v
    return None

HOUSE = {"csv_import","crm ui","manual","direct traffic","referral","conversation","other","email"}
PAID  = {"fb","ig","facebook","instagram","paid social","tiktok"}

def feats(p):
    tags = p["tags"]
    f = {}
    live = [t for t in tags if ATTENDED.search(t) and not ABSENT.search(t) and not MEMBER_EVENT.search(t)]
    f["live_webinar_attended"] = len(live)
    f["newsletter"] = any("newsletter subscriber" in t or t=="newsletter opt in" for t in tags)
    f["engaged_email"] = any(t.startswith("clicked") or t.startswith("opened") or "1 click" in t or "clicked" in t for t in tags)
    f["clicked"] = any(t.startswith("clicked") or "clicked" in t or "click" in t for t in tags)
    f["bootcamp"] = any("bootcamp" in t or "workshop" in t for t in tags)
    f["tier12"] = ("tier 1" in tags) or ("tier 2" in tags)
    f["tier5"] = "tier 5" in tags
    f["dq_tag"] = bool(tags & {"disqualify","unqualified","maybe one day","expired","bad timing","uoo vsl: not ready yet","price point sms"})
    f["suppressed"] = bool(tags & {"do not email","never send","dnd","unsubscribed","spamtrap","complainer","hard bounce","verified bad"}) or p["dnd"]
    f["hard_bad"] = bool(tags & {"spamtrap","complainer","verified bad","invalid email"})
    f["house_list"] = bool(p["attrib"] & HOUSE)
    f["paid_social"] = bool(p["attrib"] & PAID)
    f["crm_age"] = p["added"] or 0
    f["recent"] = (p["last_act"] is not None and p["last_act"] <= 90)
    f["stale"] = (p["last_act"] is None or p["last_act"] > 365)
    f["has_phone"] = bool(p["phone"])
    f["email_ok"] = bool(p["email"]) and not (tags & {"do not email","never send","verified bad","spamtrap","complainer"}) and "email" not in p["dndch"]
    f["sms_ok"] = bool(p["phone"]) and not p["dnd"] and "sms" not in p["dndch"] and not (tags & {"never send"})
    code,st,lab,inc,tier = A.lookup(p["phone"])
    f["ac"]=code; f["state"]=st; f["region"]=lab; f["ac_income"]=inc; f["ac_tier"]=tier

    cap = cfget(p,CAP_Q) or ""
    f["cap_raw"]=cap
    f["cap_band"] = ("15k+" if "15k" in cap else "10k+" if "10k" in cap else
                     "5-9k" if "$5k" in cap else "1-4k" if "$1k" in cap else
                     "unsure" if "nsure" in cap or "want to say" in cap else "")
    cap2 = cfget(p,CAP_Q2) or ""
    if not f["cap_band"] and cap2:
        f["cap_band"] = ("10k+" if ("10,000" in cap2 or "25,000" in cap2 or "50,000" in cap2 or "50000" in cap2)
                         else "5-9k" if "5,000-" in cap2 or "5,000–" in cap2 else "1-4k" if "Less than $5" in cap2 else "")
        f["cap_raw"]=f["cap_raw"] or cap2
    cap3 = cfget(p,CAP_Q3) or ""
    f["cap_confirm_5k"] = cap3.startswith("Yes - I have $5k")
    if not f["cap_band"] and f["cap_confirm_5k"]: f["cap_band"]="5-9k"; f["cap_raw"]=cap3
    for q in ("Do you have at least $5k+ in capital","Do you have at least $5000 in trading capital",
              "Do you have at least $9k+","Are you starting with $5,000 or more"):
        v = cfget(p,q)
        if v and v.lower().startswith("yes"):
            f["cap_confirm_5k"]=True
            if not f["cap_band"]: f["cap_band"]="5-9k"; f["cap_raw"]=v
        elif v and v.lower().startswith("no") and not f["cap_band"]:
            f["cap_band"]="1-4k"; f["cap_raw"]=v

    exp = cfget(p,EXP_Q) or ""
    for q in ("How many years of trading experience","How experienced are you with trading",
              "What is your level of trade experience"):
        exp = exp or (cfget(p,q) or "")
    f["exp_raw"]=exp
    f["exp_band"] = ("moderate+" if exp in ("Moderate","Put me on Wall St.") or "3+ years" in exp or "1-3" in exp or "1–3" in exp
                     else "little" if "Very Little" in exp or "1-6 month" in exp or "1–6 month" in exp
                     else "none" if exp in ("None",) or "brand new" in exp else "")
    f["income_src"] = cfget(p,INC_Q) or ""
    f["employed"]   = cfget(p,EMP_Q) or ""
    f["occupation"] = (cfget(p,OCC_Q) or "")[:120]
    f["hhi"]        = cfget(p,HHI_Q) or ""
    f["answered_survey"] = bool(p["cf"])
    f["booked"]=p["booked"]; f["showed"]=p["took_call"]
    f["dq_stage"]=p["dq"]
    return f

if __name__ == "__main__":
    F = {k: feats(p) for k,p in people.items()}
    pickle.dump(F, open("feats.pkl","wb"))
    buy=[k for k in F if people[k]["maxval"]>=4000]
    ctrl=[k for k in F if not people[k]["bought_soft"] and (F[k]["booked"] or F[k]["showed"] or F[k]["dq_stage"])]
    print(f"buyers {len(buy)} ctrl {len(ctrl)}")
    BOOL = ["live_webinar_attended","newsletter","clicked","bootcamp","tier12","tier5","dq_tag",
            "house_list","paid_social","recent","stale","has_phone","cap_confirm_5k","answered_survey",
            "booked","showed","suppressed"]
    print(f"\n{'feature':26} {'buy%':>7} {'ctl%':>7} {'lift':>7}")
    for b in BOOL:
        pb=sum(1 for k in buy if F[k][b])/len(buy); pc=sum(1 for k in ctrl if F[k][b])/len(ctrl)
        print(f"{b:26} {100*pb:6.1f}% {100*pc:6.1f}% {(pb/pc if pc else float('inf')):7.2f}")
    for cat in ("cap_band","exp_band","ac_tier"):
        print(f"\n-- {cat}")
        bc=collections.Counter(F[k][cat] for k in buy); cc=collections.Counter(F[k][cat] for k in ctrl)
        for v in set(bc)|set(cc):
            pb=bc[v]/len(buy); pc=cc[v]/len(ctrl)
            print(f"   {str(v) or '(blank)':10} buy {bc[v]:4} ({100*pb:5.1f}%)  ctl {cc[v]:5} ({100*pc:5.1f}%)  lift {(pb/pc if pc else 0):6.2f}")
    import statistics
    print("\n-- crm_age days (max across accounts)")
    for lab,g in (("buyers",buy),("ctrl",ctrl)):
        v=[F[k]["crm_age"] for k in g]
        print(f"   {lab}: median {statistics.median(v):.0f}  mean {statistics.mean(v):.0f}")
