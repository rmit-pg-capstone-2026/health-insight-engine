import sys, re, json
from pathlib import Path
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\collect_and_extract")
import collect_and_extract as ce
from bs4 import BeautifulSoup
URL_RE=re.compile(r"https?://\S+"); NUM_RE=re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
def norm(s): return re.sub(r"\s+"," ",s).strip().lower()
def stat_nums(text):
    text=URL_RE.sub(" ",text); out={}
    for m in NUM_RE.finditer(text):
        tok=m.group(0).replace(",",""); after=text[m.end():m.end()+1]
        if "." in tok or "," in m.group(0) or after=="%":
            out.setdefault(tok,text[max(0,m.start()-60):m.end()+30].replace("\n"," "))
    return out
def clean(html):
    s=BeautifulSoup(html,"lxml")
    for t in s(["script","style","noscript","nav","footer","form","svg","template"]): t.decompose()
    return s
for url in sys.argv[1:]:
    h,f=ce.fetch_html(url); res=ce.fetch_and_extract(url,html=h,final_url=f)
    print("=====",url,len(res.pages),"pages")
    ours=set(stat_nums(res.body))
    for p in res.pages:
        ph=ce.fetch_html(p)[0]
        s=clean(ph)
        ref=stat_nums(s.get_text("\n"))
        miss={k:v for k,v in ref.items() if k not in ours}
        heads=[norm(x.get_text(" ")) for x in s.find_all(["h1","h2","h3","h4"]) if norm(x.get_text(" "))]
        body_n=norm(res.body)
        mh=[x for x in heads if x not in body_n]
        if miss or mh:
            print("--",p,"| missing stat nums:",len(miss),"| missing headings:",len(mh),"of",len(heads))
            for k,v in list(miss.items())[:6]: print("     num",k,"::",v)
            for x in mh[:8]: print("     head:",x[:90])
