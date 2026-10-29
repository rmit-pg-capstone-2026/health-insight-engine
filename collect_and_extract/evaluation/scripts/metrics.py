"""Automated Layer-1 metrics: runs the repo's own extractor on the pages the finders
returned and compares it with two generic baselines on the same fetched HTML.
Nothing in the repo is modified."""
import hashlib, json, re, statistics, sys, time
from pathlib import Path

REPO = Path(r"C:\Users\saive\Documents\health-insight-engine")
sys.path.insert(0, str(REPO / "collect_and_extract"))
import collect_and_extract as ce
import lxml.html
import trafilatura
from bs4 import BeautifulSoup

OUT = Path(sys.argv[1])
found = json.loads((OUT.parent / "discovery.json").read_text())["found"]

cache = {}
_orig = ce.fetch_html
def cached(url):
    if url not in cache:
        cache[url] = _orig(url)
    return cache[url]
ce.fetch_html = cached

URL_RE = re.compile(r"https?://\S+")
NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def nums(text):
    text = URL_RE.sub(" ", text)
    out_all, out_stat = set(), set()
    for m in NUM_RE.finditer(text):
        tok = m.group(0).replace(",", "")
        out_all.add(tok)
        after = text[m.end():m.end() + 1]
        if "." in tok or "," in m.group(0) or after == "%":
            out_stat.add(tok)
    return out_all, out_stat


def soup_of(html, drop):
    s = BeautifulSoup(html, "lxml")
    for t in s(drop):
        t.decompose()
    return s


def ref_text(html):
    return soup_of(html, ["script", "style", "noscript", "nav", "footer", "form", "svg", "template"]).get_text("\n")


def chrome_lines(html):
    s = BeautifulSoup(html, "lxml")
    lines = set()
    for t in s.find_all(["nav", "footer"]):
        for l in t.get_text("\n").split("\n"):
            l = norm(l)
            if len(l) >= 3:
                lines.add(l)
    return lines


def raw_headings(html):
    s = soup_of(html, ["script", "style", "noscript", "nav", "footer", "form", "svg", "template"])
    return [norm(h.get_text(" ")) for h in s.find_all(["h1", "h2", "h3", "h4"]) if norm(h.get_text(" "))]


def raw_tables(html):
    s = soup_of(html, ["script", "style", "noscript", "nav", "footer", "form", "svg", "template"])
    tabs = [t for t in s.find_all("table") if len(t.find_all("tr")) >= 2]
    cell_text = " ".join(t.get_text(" ") for t in tabs)
    return len(tabs), cell_text


def md_tables(md):
    return len(re.findall(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", md, flags=re.M))


def md_headings(md):
    return {norm(re.sub(r"^#+\s*", "", l)) for l in md.splitlines() if re.match(r"^#{1,6}\s", l)}


def naive_text(html):
    return soup_of(html, ["script", "style", "noscript"]).get_text("\n")


def trafi(html):
    try:
        return trafilatura.extract(html, output_format="markdown", include_tables=True, include_links=False) or ""
    except Exception:
        return ""


def score(out_text, ref_nums, ref_stat, tab_nums, heads, chrome, is_md):
    n_all, n_stat = nums(out_text)
    t_all, _ = nums(tab_nums)
    hs = md_headings(out_text) if is_md else set()
    on = norm(out_text)
    lines = [norm(l) for l in out_text.splitlines()]
    lines = [l for l in lines if len(l) >= 3]
    leak = sum(1 for l in lines if l in chrome)
    return {
        "num_recall_all": len(ref_nums & n_all) / len(ref_nums) if ref_nums else None,
        "num_recall_stat": len(ref_stat & n_stat) / len(ref_stat) if ref_stat else None,
        "table_num_recall": len(t_all & n_all) / len(t_all) if t_all else None,
        "heading_text_kept": sum(1 for h in heads if h in on) / len(heads) if heads else None,
        "heading_markup_kept": (sum(1 for h in heads if h in hs) / len(heads) if heads else None) if is_md else None,
        "md_tables": md_tables(out_text) if is_md else None,
        "chars": len(out_text),
        "lines": len(lines),
        "chrome_lines_leaked": leak,
        "chrome_leak_rate": leak / len(lines) if lines else None,
    }


results = []
for i, item in enumerate(found, 1):
    url = item["url"]
    print(f"[{i}/{len(found)}] {url}", flush=True)
    rec = {"url": url, "agency": item["agency"]}
    t0 = time.time()
    try:
        html, final = ce.fetch_html(url)
        res = ce.fetch_and_extract(url, html=html, final_url=final)
    except Exception as exc:
        rec["error"] = str(exc)[:300]
        results.append(rec)
        print("   FAILED", exc, flush=True)
        continue
    rec["seconds"] = round(time.time() - t0, 1)
    rec["pages_in_doc"] = len(res.pages)
    rec["missing_pages"] = len(res.missing_pages)
    rec["data_links"] = len(res.data_links)
    rec["body_sha256"] = hashlib.sha256(res.body.encode()).hexdigest()
    rec["approx_tokens"] = len(res.body) // 4

    page_htmls = [cache[p][0] for p in res.pages if p in cache]
    ref_all, ref_stat, heads, chrome, tab_n, tab_text = set(), set(), [], set(), 0, ""
    naive, trf = [], []
    for ph in page_htmls:
        a, s = nums(ref_text(ph))
        ref_all |= a
        ref_stat |= s
        heads += raw_headings(ph)
        chrome |= chrome_lines(ph)
        n, ct = raw_tables(ph)
        tab_n += n
        tab_text += " " + ct
        naive.append(naive_text(ph))
        trf.append(trafi(ph))
    rec["raw_tables"] = tab_n
    rec["raw_headings"] = len(heads)
    rec["ref_numbers"] = len(ref_all)
    rec["ref_stat_numbers"] = len(ref_stat)
    rec["ours"] = score(res.body, ref_all, ref_stat, tab_text, heads, chrome, True)
    rec["trafilatura"] = score("\n\n".join(trf), ref_all, ref_stat, tab_text, heads, chrome, True)
    rec["naive_text"] = score("\n\n".join(naive), ref_all, ref_stat, tab_text, heads, chrome, False)
    results.append(rec)
    print(f"   pages={rec['pages_in_doc']} secs={rec['seconds']} ours stat-recall="
          f"{rec['ours']['num_recall_stat']}", flush=True)
    OUT.write_text(json.dumps(results, indent=2))

# repeat extraction (fresh fetch) on up to 4 of the smaller documents: is the output identical?
repeat = []
for rec in sorted([r for r in results if "error" not in r], key=lambda r: r["pages_in_doc"])[:4]:
    cache.clear()
    try:
        h, f = ce.fetch_html(rec["url"])
        r2 = ce.fetch_and_extract(rec["url"], html=h, final_url=f)
        repeat.append({"url": rec["url"], "identical": hashlib.sha256(r2.body.encode()).hexdigest() == rec["body_sha256"]})
    except Exception as exc:
        repeat.append({"url": rec["url"], "error": str(exc)[:200]})
OUT.write_text(json.dumps({"docs": results, "repeat": repeat}, indent=2))
print("DONE", flush=True)
