"""Final guard: ask GHL per contact whether they already hold an upcoming appointment."""
import os, sys, json, datetime
sys.path.insert(0, "/home/user/GHL-Claude")
from ghl.client import GHLClient
C = {"sms": GHLClient(os.environ["GHL_SMS_API_KEY"], os.environ["GHL_SMS_LOCATION_ID"]),
     "email": GHLClient(os.environ["GHL_EMAIL_API_KEY"], os.environ["GHL_EMAIL_LOCATION_ID"])}
CUT = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)).strftime("%Y-%m-%d %H:%M:%S")
LIVE = ("confirmed", "new", "booked", "showed")   # "showed" only matters if still in the future

def upcoming(loc, cid):
    try:
        ev = C[loc].request("GET", f"/contacts/{cid}/appointments").get("events", [])
    except Exception as exc:
        return f"lookup failed: {exc}"[:120]
    for a in ev:
        st = str(a.get("startTime") or "").replace("T", " ")[:19]
        if st > CUT and (a.get("appointmentStatus") or "").lower() in LIVE:
            return f"{a.get('appointmentStatus')} {st}"
    return None

if __name__ == "__main__":
    picked = json.load(open("picked.json"))
    flagged = {}
    for i, p in enumerate(picked, 1):
        u = upcoming(p["loc"], p["id"])
        if u: flagged[p["id"]] = u; print("  FLAG", p["name"], p["loc"], u, flush=True)
        if i % 50 == 0: print("checked", i, flush=True)
    json.dump(flagged, open("flagged_appts.json", "w"))
    print("flagged:", len(flagged), "of", len(picked))
