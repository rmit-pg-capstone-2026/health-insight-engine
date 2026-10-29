import sys, re, json
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\collect_and_extract")
import collect_and_extract as ce
import lxml.html
def norm(s): return re.sub(r"\s+"," ",s.replace("\u00a0"," ")).strip().lower()
cache={}; orig=ce.fetch_html
def cf(u):
    if u not in cache: cache[u]=orig(u)
    return cache[u]
ce.fetch_html=cf
found=[x for x in json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\discovery.json"))["found"] if x["agency"]=="AIHW"]
tot=miss=0
for it in found:
    u=it["url"]; res=ce.fetch_and_extract(u,html=cf(u)[0],final_url=cf(u)[1]); body=norm(res.body)
    n=m=0; ex=[]
    for p in res.pages:
        t=lxml.html.fromstring(cf(p)[0])
        for el in t.xpath("//*[contains(@class,'s-report-overview__text')]"):
            txt=norm(el.text_content())
            if len(txt)<20: continue
            n+=1
            if txt[:60] not in body: m+=1; ex.append(txt[:90])
        if "gp-care" in u:
            for el in t.iter():
                if isinstance(el.tag,str) and el.text and re.search(r"(?<![\d.])1\.9(?!\d)",el.text): print("GP 1.9 ::",norm(el.text)[:140], "| in body:", "1.9" in res.body)
    tot+=n; miss+=m
    print(u.split("/")[-1][:40], "overview items:",n,"missing:",m, ex[:2])
print("TOTAL overview items",tot,"missing",miss)
