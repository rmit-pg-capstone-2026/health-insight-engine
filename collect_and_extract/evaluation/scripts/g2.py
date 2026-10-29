import json
r=json.load(open(r"C:\Users\saive\AppData\Local\Temp\hie_eval\gaps.json"))
for x in r:
    print(x["url"].split("/")[-1][:34], x["agency"], "nums:", x["other_num_samples"], "| heads other:", x["other_head_samples"])
S=lambda k: sum(x[k] for x in r)
print("TOTAL ref_stat",S("ref_stat"),"missing",S("missing"),"fig",S("missing_in_figure_text"),"other",S("missing_other"))
print("recall", round(1-S("missing")/S("ref_stat"),4), "excl fig", round(1-S("missing_other")/S("ref_stat"),4))
print("heads",S("heads"),"missing",S("heads_missing"),"boiler",S("heads_missing_boiler"),"fig titles",S("heads_missing_figure_titles"),"other",S("heads_missing_other"))
print("content-heading retention (excl. boilerplate):", round(1-(S("heads_missing")-S("heads_missing_boiler"))/(S("heads")-S("heads_missing_boiler")),4) if False else round(1-(S("heads_missing_figure_titles")+S("heads_missing_other"))/(S("heads")-S("heads_missing_boiler")),4))
