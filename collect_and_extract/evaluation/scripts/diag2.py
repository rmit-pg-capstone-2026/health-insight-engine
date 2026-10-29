import sys, re
sys.path.insert(0, r"C:\Users\saive\Documents\health-insight-engine\collect_and_extract")
import collect_and_extract as ce
import lxml.html
u="https://www.aihw.gov.au/reports/health-welfare-expenditure/health-expenditure-australia-2024-25/contents/overview/total-health-spending"
h,f=ce.fetch_html(u)
res=ce.fetch_and_extract(u,html=h,final_url=f)
print("md chars",len(res.body), "has 160.8:", "160.8" in res.body, "has 'Figure 1a':", "Figure 1a" in res.body, "has 290.7:", "290.7" in res.body)
t=lxml.html.fromstring(h)
for el in t.iter():
    if isinstance(el.tag,str) and el.text and "160.8 billion" in el.text:
        chain=[]; p=el
        while p is not None and len(chain)<9:
            chain.append(p.tag+("."+p.get("class").split()[0] if p.get("class") else "")+("#"+p.get("id") if p.get("id") else "")); p=p.getparent()
        print("FOUND in", " < ".join(chain)); print("   text:", el.text.strip()[:160])
# attributes containing it
for el in t.iter():
    if isinstance(el.tag,str):
        for k,v in el.attrib.items():
            if "160.8" in v: print("ATTR", el.tag, k, len(v), v[:120].replace("\n"," "))
i=res.body.find("Figure 1")
print("--- body around Figure 1:"); print(res.body[max(0,i-200):i+600] if i>=0 else "no 'Figure 1' in body")
