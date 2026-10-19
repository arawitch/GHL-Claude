import os, sys, json, time
sys.path.insert(0,"/home/user/GHL-Claude")
from ghl.client import GHLClient
KEEP = ("id","firstName","lastName","contactName","email","phone","dnd","dndSettings",
        "inboundDndSettings","tags","dateAdded","dateUpdated","lastActivity","source","type",
        "opportunities","assignedTo","timezone","country","customFields","additionalPhones")
for label, tk, loc in [("sms","GHL_SMS_API_KEY","GHL_SMS_LOCATION_ID"),("email","GHL_EMAIL_API_KEY","GHL_EMAIL_LOCATION_ID")]:
    c = GHLClient(os.environ[tk], os.environ[loc])
    t0=time.time(); n=0
    with open(f"contacts_{label}.jsonl","w") as f:
        for ct in c.search_contacts(page_limit=100):
            att = (ct.get("lastAttributionSource") or {})
            row = {k: ct.get(k) for k in KEEP}
            row["sessionSource"] = att.get("sessionSource"); row["medium"]=att.get("medium")
            row["utmSource"]=att.get("utmSource"); row["mediumId"]=att.get("mediumId")
            f.write(json.dumps(row, default=str)+"\n"); n+=1
            if n % 5000 == 0: print(label, n, round(time.time()-t0), flush=True)
    print("DONE", label, n, round(time.time()-t0), flush=True)
