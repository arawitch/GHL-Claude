import os, sys, json, time
sys.path.insert(0,"/home/user/GHL-Claude")
from ghl.client import GHLClient
now=int(time.time()*1000); end=now+365*86400*1000; start=now-400*86400*1000
out=[]
for label, tk, loc in [("sms","GHL_SMS_API_KEY","GHL_SMS_LOCATION_ID"),("email","GHL_EMAIL_API_KEY","GHL_EMAIL_LOCATION_ID")]:
    c = GHLClient(os.environ[tk], os.environ[loc])
    for cal in c.get("/calendars/").get("calendars",[]):
        try: ev = c.get("/calendars/events", calendarId=cal["id"], startTime=str(start), endTime=str(end)).get("events",[])
        except Exception as e: print("ERR",cal.get("name"),repr(e)[:120]); continue
        for e in ev:
            out.append({"loc":label,"cal":cal.get("name"),"id":e.get("id"),"contactId":e.get("contactId"),
                        "title":e.get("title"),"startTime":e.get("startTime"),"status":e.get("appointmentStatus")})
json.dump(out, open("events.json","w"), indent=0)
print("events:",len(out))
from collections import Counter
print(Counter(e["status"] for e in out))
import datetime
nowi=datetime.datetime.now(datetime.timezone.utc)
fut=[e for e in out if e["startTime"] and datetime.datetime.fromisoformat(e["startTime"])>nowi]
print("future:",len(fut), Counter(e["status"] for e in fut))
for e in fut: print(" ", e["loc"], e["status"], e["startTime"], e["cal"][:30], e["contactId"])
