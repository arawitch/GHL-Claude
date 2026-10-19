import os, sys, json, time
sys.path.insert(0,"/home/user/GHL-Claude")
from ghl.client import GHLClient
K=("id","contactId","pipelineId","pipelineStageId","status","name","monetaryValue","createdAt","updatedAt","lastStatusChangeAt","lastStageChangeAt","source","assignedTo")
c = GHLClient(os.environ["GHL_EMAIL_API_KEY"], os.environ["GHL_EMAIL_LOCATION_ID"])
n=0; page=1; sa=None; sai=None; t0=time.time(); seen=set()
with open("opps_email.jsonl","w") as f:
    while True:
        p={"location_id":c.location_id,"limit":100}
        if sa is None: p["page"]=page
        else: p["startAfter"]=sa; p["startAfterId"]=sai
        rows = c.request("GET","/opportunities/search", params=p).get("opportunities",[])
        if not rows: break
        new=0
        for o in rows:
            if o["id"] in seen: continue
            seen.add(o["id"]); new+=1
            f.write(json.dumps({k:o.get(k) for k in K}, default=str)+"\n"); n+=1
        if new==0: print("no new, stop", n); break
        lastrow = rows[-1]
        sa = lastrow.get("sort",[None])[0] if lastrow.get("sort") else lastrow.get("updatedAt")
        sai = lastrow.get("id"); page+=1
        if page%50==0: print(n, round(time.time()-t0), flush=True)
        if page>500: print("cap"); break
print("DONE email", n, flush=True)
