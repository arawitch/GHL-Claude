import os, sys, json, time
sys.path.insert(0,"/home/user/GHL-Claude")
from ghl.client import GHLClient
CUT = (time.time() - 200*86400)*1000
K=("id","contactId","lastMessageDate","lastMessageType","lastMessageDirection","lastCallTimestamp","lastCallStatus","lastOutboundMessageAction","unreadCount","type","phone","email")
for label, tk, loc in [("sms","GHL_SMS_API_KEY","GHL_SMS_LOCATION_ID"),("email","GHL_EMAIL_API_KEY","GHL_EMAIL_LOCATION_ID")]:
    c = GHLClient(os.environ[tk], os.environ[loc]); n=0; old=0; last=None; t0=time.time(); seen=set()
    with open(f"conv_{label}.jsonl","w") as f:
        while True:
            p={"locationId":c.location_id,"limit":100,"sortBy":"last_message_date","sort":"desc"}
            if last: p["startAfterDate"]=last
            rows = c.request("GET","/conversations/search", params=p).get("conversations",[])
            if not rows: break
            new=0
            for cv in rows:
                if cv["id"] in seen: continue
                seen.add(cv["id"]); new+=1
                lmd = cv.get("lastMessageDate") or 0
                if lmd and lmd < CUT: old+=1
                f.write(json.dumps({k:cv.get(k) for k in K}, default=str)+"\n"); n+=1
            if new==0: print(label,"no new rows, stopping at",n,flush=True); break
            if old>200: print(label,"past cutoff at",n,flush=True); break
            nd=[cv.get("lastMessageDate") for cv in rows if cv.get("lastMessageDate")]
            last = min(nd) if nd else None
            if n % 5000 < 100: print(label,n,round(time.time()-t0),flush=True)
    print("DONE",label,n,flush=True)
