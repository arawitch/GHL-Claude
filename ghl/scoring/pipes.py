import os,json,requests
B="https://services.leadconnectorhq.com"
for L in ("SMS","EMAIL"):
    tok=os.environ[f"GHL_{L}_API_KEY"]; loc=os.environ[f"GHL_{L}_LOCATION_ID"]
    h={"Authorization":f"Bearer {tok}","Version":"2021-07-28","Accept":"application/json"}
    r=requests.get(B+"/opportunities/pipelines",headers=h,params={"locationId":loc},timeout=60)
    print("==",L,r.status_code)
    if r.status_code!=200: print(r.text[:200]); continue
    ps=r.json().get("pipelines",[])
    json.dump(ps,open(f"pipes_{L}.json","w"))
    for p in ps:
        print(" ",p["name"],"|", " > ".join(s["name"] for s in p.get("stages",[])))
