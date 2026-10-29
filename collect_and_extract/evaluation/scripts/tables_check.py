import sys, re, json, random
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\collect_and_extract")
import collect_and_extract as ce
import lxml.html
from bs4 import BeautifulSoup
def norm(s):
    s=re.sub(chr(92)*2+"([|*_])",lambda m:m.group(1),s); s=s.replace("**","").replace(chr(160)," ")
    return re.sub(r"\s+"," ",s).strip().lower()
cache={}; orig=ce.fetch_html
def cf(u):
    if u not in cache: cache[u]=orig(u)
    return cache[u]
ce.fetch_html=cf
def md_tables(md):
    tabs=[]; cur=[]
    for l in md.splitlines()+[""]:
        if l.strip().startswith("|"):
            cells=[norm(c) for c in l.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?",c) for c in cells if c): continue
            cur.append(cells)
        else:
            if cur: tabs.append(cur); cur=[]
    return tabs
def raw_tabs(html):
    s=BeautifulSoup(html,"lxml")
    for t in s(["script","style","noscript","nav","footer","form","svg","template"]): t.decompose()
    out=[]
    for t in s.find_all("table"):
        rows=[[norm(c.get_text(" ")) for c in r.find_all(["td","th"])] for r in t.find_all("tr")]
        rows=[r for r in rows if r]
        if len(rows)>=2 and max(len(r) for r in rows)>=2 and sum(1 for r in rows for c in r if c)>=4:
            out.append(rows)
    return out
found=json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\discovery.json"))["found"]
pool={"AIHW":[],"ABS":[]}; bodies={}
for it in found:
    u=it["url"]; h,f=cf(u); res=ce.fetch_and_extract(u,html=h,final_url=f)
    mt=md_tables(res.body); bodies[u]=res.body
    for p in res.pages:
        for rt in raw_tabs(cf(p)[0]): pool[it["agency"]].append((u,p,rt,mt))
print({k:len(v) for k,v in pool.items()})
random.seed(2026)
sample=random.sample(pool["AIHW"],5)+random.sample(pool["ABS"],5)
rows=[]
for u,p,rt,mt in sample:
    raw_cells=[c for r in rt for c in r if c]
    best=None
    for m in mt:
        mc={c for r in m for c in r if c}
        sc=sum(1 for c in raw_cells if c in mc)/len(raw_cells)
        if best is None or sc>best[0]: best=(sc,m)
    sc,m=best if best else (0,[])
    shape_raw=(len(rt),max(len(r) for r in rt)); shape_md=(len(m),max((len(r) for r in m),default=0))
    # positional check when shapes match
    pos=None
    if m and len(m)==len(rt):
        tot=ok=0
        for rr,mr in zip(rt,m):
            for j,c in enumerate(rr):
                if not c: continue
                tot+=1; ok+= (j<len(mr) and mr[j]==c)
        pos=ok/tot if tot else None
    rows.append({"doc":u.rstrip("/").split("/")[-1][:34],"page":p.split("/")[-1][:30],"raw_shape":shape_raw,"md_shape":shape_md,"cells":len(raw_cells),"cell_recall":round(sc,3),"positional_match":None if pos is None else round(pos,3)})
for r in rows: print(r)
tc=sum(r["cells"] for r in rows); tm=sum(r["cells"]*r["cell_recall"] for r in rows)
print("TOTAL cells",tc,"found",round(tm),"=",round(tm/tc*100,1),"%","| tables with every cell found:",sum(1 for r in rows if r["cell_recall"]==1.0),"of",len(rows))
print("tables with positional match 100%:",sum(1 for r in rows if r["positional_match"]==1.0),"of",sum(1 for r in rows if r["positional_match"] is not None))
# the seven unexplained values
targets={"hearing-health":["1.9","2.9","31","51","55"],"2025":["8.44","80.56"]}
NUM=re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
for it in found:
    u=it["url"]; key="hearing-health" if "hearing-health" in u else ("2025" if "/2025" in u else None)
    if not key: continue
    res=ce.fetch_and_extract(u,html=cf(u)[0],final_url=cf(u)[1])
    for p in res.pages:
        t=lxml.html.fromstring(cf(p)[0])
        for el in t.iter():
            if not isinstance(el.tag,str): continue
            for txt,own in ((el.text,el),(el.tail,el.getparent())):
                if not txt or own is None: continue
                for tok in targets[key]:
                    if re.search(r"(?<![\d.])"+re.escape(tok)+r"(?![\d])",txt):
                        chain=[];q=own
                        while q is not None and len(chain)<4:
                            chain.append(q.tag+("."+q.get("class").split()[0] if q.get("class") else "")); q=q.getparent()
                        print(key,tok,"|"," < ".join(chain),"|",re.sub(r"\s+"," ",txt)[:110])
