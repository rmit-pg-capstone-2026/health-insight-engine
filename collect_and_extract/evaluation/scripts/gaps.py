import sys, re, json
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\collect_and_extract")
import collect_and_extract as ce
import lxml.html
from bs4 import BeautifulSoup
URL_RE=re.compile(r"https?://\S+"); NUM_RE=re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
def norm(s): return re.sub(r"\s+"," ",s).strip().lower()
def stat_set(text):
    text=URL_RE.sub(" ",text); out=set()
    for m in NUM_RE.finditer(text):
        tok=m.group(0).replace(",",""); after=text[m.end():m.end()+1]
        if "." in tok or "," in m.group(0) or after=="%": out.add(tok)
    return out
def clean(html):
    s=BeautifulSoup(html,"lxml")
    for t in s(["script","style","noscript","nav","footer","form","svg","template"]): t.decompose()
    return s
BOILER={"citation","other ways to browse","on this page in this section","on this page","related content","share this page","contents","skip to content","feedback","cite","download","data","resources","related"}
FIG=re.compile(r"^(figure|table|chart|map)\s*\w+[:.]",re.I)
def figure_text_numbers(html):
    """numbers appearing only inside screen-reader / chart-widget text or image alt text"""
    t=lxml.html.fromstring(html); found=set()
    def chart_ctx(el):
        p=el
        while p is not None:
            c=(p.get("class") or "").lower() if isinstance(p.tag,str) else ""
            if "sr-only" in c or "viz" in c or "tableau" in c or "chart" in c: return True
            p=p.getparent()
        return False
    for el in t.iter():
        if not isinstance(el.tag,str): continue
        if el.text and chart_ctx(el): found|=stat_set(el.text)
        if el.tail and el.getparent() is not None and chart_ctx(el.getparent()): found|=stat_set(el.tail)
        alt=el.get("alt") or ""
        if alt: found|=stat_set(alt)
    return found
rows=[]
cache={}
orig=ce.fetch_html
def cf(u):
    if u not in cache: cache[u]=orig(u)
    return cache[u]
ce.fetch_html=cf
d=json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\discovery.json"))["found"]
for item in d:
    u=item["url"]; h,f=cf(u); res=ce.fetch_and_extract(u,html=h,final_url=f)
    ours=stat_set(res.body); bodyn=norm(res.body)
    ref=set(); fig=set(); heads=[]
    for p in res.pages:
        ph=cf(p)[0]; s=clean(ph)
        ref|=stat_set(s.get_text("\n")); fig|=figure_text_numbers(ph)
        heads+=[norm(x.get_text(" ")) for x in s.find_all(["h1","h2","h3","h4"]) if norm(x.get_text(" "))]
    miss=ref-ours; miss_fig=miss&fig; miss_other=miss-fig
    mh=[x for x in heads if x not in bodyn]
    mb=[x for x in mh if x in BOILER]; mf=[x for x in mh if x not in BOILER and FIG.match(x)]; mo=[x for x in mh if x not in BOILER and not FIG.match(x)]
    rows.append({"url":u,"agency":item["agency"],"ref_stat":len(ref),"missing":len(miss),"missing_in_figure_text":len(miss_fig),"missing_other":len(miss_other),
      "recall":round(1-len(miss)/len(ref),4) if ref else None,"recall_excl_figure_text":round(1-len(miss_other)/len(ref),4) if ref else None,
      "heads":len(heads),"heads_missing":len(mh),"heads_missing_boiler":len(mb),"heads_missing_figure_titles":len(mf),"heads_missing_other":len(mo),"other_head_samples":mo[:6],"other_num_samples":sorted(miss_other)[:8]})
    print(u.rstrip("/").split("/")[-1][:40], rows[-1]["ref_stat"], rows[-1]["missing"], rows[-1]["missing_in_figure_text"], rows[-1]["missing_other"], "| heads", rows[-1]["heads"], rows[-1]["heads_missing"], rows[-1]["heads_missing_boiler"], rows[-1]["heads_missing_figure_titles"], rows[-1]["heads_missing_other"], flush=True)
json.dump(rows,open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\gaps.json","w"),indent=2)
print("DONE")
