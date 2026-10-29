import json, sys, time
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine")
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\pipeline")
import discover
settings = json.load(open(r"C:\Users\saive\Documents\health-insight-engine\pipeline\collect_settings.json"))
t=time.time()
res = discover.find(settings)
res["seconds"]=round(time.time()-t,1)
json.dump(res, open(sys.argv[1],"w"), indent=2)
print("since", res["since"], "found", len(res["found"]), "skipped", len(res["skipped"]), "errors", res["errors"], "secs", res["seconds"])
from collections import Counter
print(Counter(f["agency"] for f in res["found"]))
for f in res["found"]: print(f["agency"], f["release_date"], f["url"])
for s in res["skipped"]: print("SKIP", s)
