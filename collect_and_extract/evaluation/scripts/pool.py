import json
d=json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\metrics.json"))["docs"]
docs=[x for x in d if x["ref_stat_numbers"]>0]  # drops hearing-health (reference page not cached in pass 1)
print("docs used", len(docs), "of", len(d))
for m in ("ours","trafilatura","naive_text"):
    ra=sum(x["ref_numbers"] for x in docs); rs=sum(x["ref_stat_numbers"] for x in docs); rh=sum(x["raw_headings"] for x in docs)
    all_=sum((x[m]["num_recall_all"] or 0)*x["ref_numbers"] for x in docs)
    stat=sum((x[m]["num_recall_stat"] or 0)*x["ref_stat_numbers"] for x in docs)
    ht=sum((x[m]["heading_text_kept"] or 0)*x["raw_headings"] for x in docs)
    hm=sum((x[m]["heading_markup_kept"] or 0)*x["raw_headings"] for x in docs) if m!="naive_text" else None
    leak=sum(x[m]["chrome_lines_leaked"] for x in docs); lines=sum(x[m]["lines"] for x in docs)
    tabs=sum(x[m]["md_tables"] or 0 for x in docs) if m!="naive_text" else None
    print(m, f"all-num {all_/ra*100:.1f}%  stat-num {stat/rs*100:.1f}%  heading-text {ht/rh*100:.1f}%", f"heading-markup {hm/rh*100:.1f}%" if hm is not None else "", f"leak {leak}/{lines} = {leak/lines*100:.2f}%", f"md-tables {tabs}" if tabs is not None else "")
print("raw tables (docs used)", sum(x["raw_tables"] for x in docs), " numbers pooled: ref_all", sum(x["ref_numbers"] for x in docs), "ref_stat", sum(x["ref_stat_numbers"] for x in docs))
tn=lambda m: sum((x[m]["table_num_recall"] or 0) for x in docs if x[m]["table_num_recall"] is not None)/sum(1 for x in docs if x[m]["table_num_recall"] is not None)*100
print("table-number recall (mean of docs with tables):", {m:round(tn(m),1) for m in ("ours","trafilatura","naive_text")})
ab=[x for x in docs if x["agency"]=="ABS"]; ai=[x for x in docs if x["agency"]=="AIHW"]
for name,s in (("ABS",ab),("AIHW",ai)):
    for m in ("ours","trafilatura"):
        rs=sum(x["ref_stat_numbers"] for x in s); stat=sum((x[m]["num_recall_stat"] or 0)*x["ref_stat_numbers"] for x in s)
        print(name,m,f"stat recall pooled {stat/rs*100:.1f}% over {rs} numbers")
print("time: total secs",round(sum(x["seconds"] for x in d),1),"pages",sum(x["pages_in_doc"] for x in d),"=> secs/page",round(sum(x["seconds"] for x in d)/sum(x["pages_in_doc"] for x in d),2))
print("per-doc secs: median", sorted(x["seconds"] for x in d)[len(d)//2], "max", max(x["seconds"] for x in d))
print("approx tokens: total", sum(x["approx_tokens"] for x in d), "median", sorted(x["approx_tokens"] for x in d)[len(d)//2], "max", max(x["approx_tokens"] for x in d))
