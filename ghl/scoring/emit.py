import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pickle, csv, collections, os, statistics
people=pickle.load(open("people.pkl","rb")); F=pickle.load(open("feats.pkl","rb"))
OUT="/mnt/project-files/lead-scoring/"
os.makedirs(OUT,exist_ok=True)

# overlap with the sibling thread's win-back universe
wb=set()
try:
    for r in csv.DictReader(open("/mnt/project-files/signal-pilot/signal-pilot-all-segments.csv")):
        e=(r.get("email") or "").strip().lower()
        if e: wb.add(e)
except Exception as e: print("winback read failed",e)
print("win-back universe emails loaded:",len(wb))

COLS=["band","ht_score","sp_score","email","phone","first_name","last_name",
      "sms_contact_id","main_contact_id","in_both_accounts",
      "capital_answer","capital_band","experience","primary_income_source","employed",
      "household_income","occupation",
      "live_webinars_attended","newsletter_sub","clicked_campaign","bootcamp_signup",
      "lead_tier_tags","disqualified","disqualify_reason",
      "area_code","state_region","area_median_income_k","area_income_tier",
      "attribution","days_in_crm","days_since_activity","past_purchase_value",
      "email_ok","sms_ok","in_winback_list","ht_reasons","sp_reasons"]

def row(k):
    p=people[k]; f=F[k]
    dqr=[]
    dqr += sorted(p["tags"] & {"disqualify","unqualified","maybe one day","expired","bad timing","uoo vsl: not ready yet","price point sms"})
    dqr += p["dq_stages"]
    return {
     "band":f["band"],"ht_score":f["ht"],"sp_score":f["sp"],
     "email":p["email"],"phone":p["phone"],"first_name":p["first"],"last_name":p["last"],
     "sms_contact_id":p["ids"].get("SMS",""),"main_contact_id":p["ids"].get("EMAIL",""),
     "in_both_accounts":len(p["accts"])==2,
     "capital_answer":f["cap_raw"],"capital_band":f["cap_band"],"experience":f["exp_raw"],
     "primary_income_source":f["income_src"],"employed":f["employed"],
     "household_income":f["hhi"],"occupation":f["occupation"],
     "live_webinars_attended":f["live_webinar_attended"],"newsletter_sub":f["newsletter"],
     "clicked_campaign":f["clicked"],"bootcamp_signup":f["bootcamp"],
     "lead_tier_tags":"; ".join(sorted(t for t in p["tags"] if t.startswith("tier "))),
     "disqualified":f["dq_tag"] or f["dq_stage"],"disqualify_reason":"; ".join(dqr),
     "area_code":f["ac"] or "","state_region":f["state"],
     "area_median_income_k":f["ac_income"] or "","area_income_tier":f["ac_tier"],
     "attribution":"; ".join(sorted(p["attrib"]))[:80],
     "days_in_crm":p["added"],"days_since_activity":p["last_act"],
     "past_purchase_value":f"{p['maxval']:.0f}" if p["maxval"] else "",
     "email_ok":f["email_ok"],"sms_ok":f["sms_ok"],
     "in_winback_list":(p["email"] in wb) if p["email"] else False,
     "ht_reasons":f["ht_why"],"sp_reasons":f["sp_why"],
    }

def write(fn, keys, sortkey):
    keys=sorted(keys,key=sortkey)
    with open(OUT+fn,"w",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=COLS); w.writeheader()
        for k in keys: w.writerow(row(k))
    print(f"  {fn:46} {len(keys):6} rows")

ALL=list(F)
write("all-contacts-scored.csv", ALL, lambda k:(F[k]["band"],-F[k]["ht"],-F[k]["sp"]))

ht=[k for k in ALL if F[k]["band"].startswith(("1.","2."))]
write("high-ticket-call-list.csv", ht, lambda k:-F[k]["ht"])
htc=[k for k in ALL if F[k]["band"].startswith("3.")]
write("high-ticket-test-band.csv", htc, lambda k:-F[k]["ht"])

dq=[k for k in ALL if (F[k]["dq_tag"] or F[k]["dq_stage"]) and not people[k]["bought_soft"]
    and (F[k]["email_ok"] or F[k]["sms_ok"])]
write("disqualified-best-for-99mo.csv", dq, lambda k:-F[k]["sp"])

prime=[k for k in dq if F[k]["cap_band"] in ("1-4k","unsure")]
write("disqualified-capital-1k-4k.csv", prime, lambda k:-F[k]["sp"])

sp=[k for k in ALL if F[k]["band"].startswith(("4.","5.")) ]
write("signal-pilot-priority.csv", sp, lambda k:-F[k]["sp"])

# high income area codes reference
with open(OUT+"area-code-income-reference.csv","w",newline="") as fh:
    import areacodes as A
    cnt=collections.Counter()
    for p in people.values():
        c,st,lab,inc,t=A.lookup(p["phone"])
        if c: cnt[c]+=1
    w=csv.writer(fh); w.writerow(["area_code","state_region","principal_area","approx_median_household_income_k","income_tier","contacts_in_list","reachable_contacts"])
    reach=collections.Counter()
    for k,p in people.items():
        c,st,lab,inc,t=A.lookup(p["phone"])
        if c and (F[k]["email_ok"] or F[k]["sms_ok"]): reach[c]+=1
    rows=[]
    for c,n in cnt.items():
        st,lab,inc=A.AC.get(c,("US?","Unmapped US area code",None))
        rows.append((-(inc or -1),-n,c,st,lab,inc,A.tier(inc),n,reach[c]))
    rows.sort()
    for r in rows: w.writerow([r[2],r[3],r[4],r[5] if r[5] is not None else "",r[6],r[7],r[8]])
print(f"  area-code-income-reference.csv                  {len(rows):6} rows")

# summary numbers for the writeup
print("\n--- summary ---")
c=collections.Counter(F[k]["band"] for k in ALL)
for b in sorted(c):
    g=[k for k in ALL if F[k]["band"]==b]
    reach=sum(1 for k in g if F[k]["email_ok"] or F[k]["sms_ok"])
    inwb=sum(1 for k in g if people[k]["email"] in wb)
    nb=sum(1 for k in g if people[k]["maxval"]>=4000)
    print(f"{b:28} n={c[b]:6} reachable={reach:6} already_in_winback={inwb:6} known_4k_buyers={nb:4}")
print()
print("prime 99/mo pool overlap with win-back list:",sum(1 for k in prime if people[k]["email"] in wb),"of",len(prime))
