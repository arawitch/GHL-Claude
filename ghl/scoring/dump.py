import os, json, sys, time, requests
B="https://services.leadconnectorhq.com"
label=sys.argv[1]
tok=os.environ[f"GHL_{label}_API_KEY"]; loc=os.environ[f"GHL_{label}_LOCATION_ID"]
h={"Authorization":f"Bearer {tok}","Version":"2021-07-28","Accept":"application/json","Content-Type":"application/json"}
s=requests.Session(); s.headers.update(h)

def post(path,payload,tries=6):
    for i in range(tries):
        try:
            r=s.post(B+path,json=payload,timeout=180)
        except Exception as e:
            print("  net err",e,flush=True); time.sleep(2**i); continue
        if r.status_code==200: return r.json()
        body=r.text[:200].lower()
        if r.status_code in (429,500,502,503,504) or (r.status_code==401 and ("timed out" in body or "invalid private integration token" in body)):
            print("  retry",r.status_code,body[:80],flush=True); time.sleep(2**i); continue
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    raise RuntimeError("exhausted retries")

out=open(f"contacts_{label}.jsonl","w")
after=None; n=0; t0=time.time()
while True:
    p={"locationId":loc,"pageLimit":100,"sort":[{"field":"dateAdded","direction":"asc"}]}
    if after: p["searchAfter"]=after
    body=post("/contacts/search",p)
    batch=body.get("contacts",[])
    if not batch: break
    for c in batch: out.write(json.dumps(c)+"\n")
    n+=len(batch)
    after=batch[-1].get("searchAfter")
    if n%5000<100: print(f"{label} {n} {int(time.time()-t0)}s",flush=True)
    if not after: break
out.close()
print(f"{label} DONE contacts={n} {int(time.time()-t0)}s",flush=True)

# opportunities
out=open(f"opps_{label}.jsonl","w")
n=0; page=1; sa=None; sai=None
while True:
    q={"location_id":loc,"limit":100}
    if sa: q["startAfter"]=sa; q["startAfterId"]=sai
    else: q["page"]=page
    for i in range(6):
        try: r=s.get(B+"/opportunities/search",params=q,timeout=180)
        except Exception as e: print("  net",e,flush=True); time.sleep(2**i); continue
        break
    if r.status_code!=200:
        if "START_AFTER" in r.text.upper() or "startAfter" in r.text:
            pass
        else:
            print("opps err",r.status_code,r.text[:300],flush=True); break
    body=r.json() if r.status_code==200 else {}
    rows=body.get("opportunities",[])
    if not rows: break
    for o in rows: out.write(json.dumps(o)+"\n")
    n+=len(rows)
    last=rows[-1]
    srt=last.get("sort")
    if srt and len(srt)==2: sa,sai=srt[0],srt[1]
    else: page+=1
    if n%2000<100: print(f"{label} opps {n}",flush=True)
out.close()
print(f"{label} DONE opps={n}",flush=True)
