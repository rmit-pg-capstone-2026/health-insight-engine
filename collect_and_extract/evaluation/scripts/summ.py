import json, statistics as st
d=json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\metrics.json"))
docs=[x for x in d["docs"] if "error" not in x]
print("errors:", [x for x in d["docs"] if "error" in x])
def f(v): return "  -  " if v is None else f"{v*100:5.1f}"
print(f"{'doc':44} pg miss sec  tok  tab(raw/ours/trf) refNum refStat | statRecall ours/trf/naive | allRecall o/t/n | tabNum o/t/n | headTxt o/t | headMk o/t | chromeLeak o/t/n(%)")
for x in docs:
    o,t,n=x["ours"],x["trafilatura"],x["naive_text"]
    name=x["url"].rstrip("/").split("/")[-1][:30]
    print(f"{x['agency']:4}{name:30} {x['pages_in_doc']:3} {x['missing_pages']:2} {x['seconds']:5} {x['approx_tokens']:6} {x['raw_tables']:3}/{o['md_tables']:3}/{t['md_tables']:3} {x['ref_numbers']:5} {x['ref_stat_numbers']:5} | "
      f"{f(o['num_recall_stat'])} {f(t['num_recall_stat'])} {f(n['num_recall_stat'])} | {f(o['num_recall_all'])} {f(t['num_recall_all'])} {f(n['num_recall_all'])} | "
      f"{f(o['table_num_recall'])} {f(t['table_num_recall'])} {f(n['table_num_recall'])} | {f(o['heading_text_kept'])} {f(t['heading_text_kept'])} | {f(o['heading_markup_kept'])} {f(t['heading_markup_kept'])} | "
      f"{f(o['chrome_leak_rate'])} {f(t['chrome_leak_rate'])} {f(n['chrome_leak_rate'])}")
def agg(key,sub):
    v=[x[sub][key] for x in docs if x[sub][key] is not None]
    return (round(st.mean(v)*100,1), round(min(v)*100,1)) if v else None
print()
for key in ("num_recall_all","num_recall_stat","table_num_recall","heading_text_kept","heading_markup_kept","chrome_leak_rate"):
    print(key, {m:agg(key,m) for m in ("ours","trafilatura","naive_text")})
tot=lambda k,m: sum(x[m][k] for x in docs)
print("tables raw", sum(x["raw_tables"] for x in docs), "ours", tot("md_tables","ours"), "trafilatura", tot("md_tables","trafilatura"))
print("leaked lines total", {m:tot("chrome_lines_leaked",m) for m in ("ours","trafilatura","naive_text")}, "lines", {m:tot("lines",m) for m in ("ours","trafilatura","naive_text")})
print("pages total", sum(x["pages_in_doc"] for x in docs), "secs total", round(sum(x["seconds"] for x in docs),1), "tokens total", sum(x["approx_tokens"] for x in docs), "data links", sum(x["data_links"] for x in docs), "missing", sum(x["missing_pages"] for x in docs))
print("by agency:")
for ag in ("AIHW","ABS"):
    s=[x for x in docs if x["agency"]==ag]
    print(ag, len(s), "docs", sum(x["pages_in_doc"] for x in s), "pages",
      "statRecall ours", round(st.mean(x["ours"]["num_recall_stat"] for x in s if x["ours"]["num_recall_stat"] is not None)*100,1),
      "trf", round(st.mean(x["trafilatura"]["num_recall_stat"] for x in s if x["trafilatura"]["num_recall_stat"] is not None)*100,1))
print("repeat:", d["repeat"])
