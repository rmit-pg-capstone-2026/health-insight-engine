# Manual health engine sandbox

A standalone, disposable proof-of-concept. It is **not** connected to any
team repo, git history, or shared codebase — it exists purely to demo one
thing on my own machine before handing off to the LLM team.

## What this proves

That a minimal, fully manual URL-in -> Markdown-out pipeline works end to
end for two sources (AIHW and ABS) that turned out to need almost entirely
different extraction strategies, without any of the discovery/dedup
machinery from the other sandboxes.

## 1. Collecting URLs

**Two-phase design: collect first, extract second.** Nothing hits the
network while URLs are being typed — `collect_urls()` just gathers them into
plain lists (mandatory URL 1 and 2, then a "do you have more?" loop),
matching the original sketch. Input mistakes stay cheap because fetching
only starts once both sources' lists are confirmed. Each URL is checked
against the expected agency domain (`aihw.gov.au` / `abs.gov.au`, including
subdomains) as it's typed — a wrong-source or malformed URL is rejected and
re-prompted (mandatory slots) or dropped with a warning (optional slots),
before any network request is made.

**Fetching.** Plain `requests.get()` with a custom User-Agent and a 20s
timeout, wrapped in a `FetchError` if the request fails or returns a bad
status. A failed URL is skipped, not retried, so one bad URL doesn't kill
the whole batch.

## 2. AIHW extraction

**Multi-page reports.** AIHW publishes long reports as many pages under a
shared `.../contents/<section>` path (a sidebar table of contents), not as
HTTP pagination. `discover_report_pages()` detects this shape and pulls
every sibling section link from the table of contents; `fetch_and_extract()`
fetches all of them (politely, with a delay between requests, capped at
`MAX_REPORT_PAGES`) and stitches them into one combined markdown document,
so giving it any single section URL (e.g. the "About" page) captures the
whole report, not just that one section.

**A single trafilatura pass** (`trafilatura.extract(html,
output_format="markdown", include_tables=True)`) handles the actual
HTML-to-Markdown conversion for each AIHW page — this works cleanly for
AIHW's page structure, unlike ABS (see below).

**Accordion widgets get converted to real headings first.**
`_convert_aihw_accordions()` runs before trafilatura on every AIHW page.
Confirmed widespread on real reports (58 of 81 pages on the dementia report,
11 of 37 on the First Nations burden-of-disease report, 2–22 accordion
sections per page): a topic label like "Impact on health, aged care and
social systems" is a `<button class="w-accordion__item__trigger">`, not a
heading tag at all. trafilatura still keeps the accordion's own text content
(the collapsed-by-default styling is presentational only, not reflected in
the fetched HTML) — but with no heading marking where one topic ends and the
next begins, unrelated topics were silently merging into one undifferentiated
block (confirmed: a "Childhood dementia" section flowed directly into an
unrelated "data gaps and limitations" topic with zero boundary between them).
The fix converts each trigger's own direct text (not its nested "Expand"
button label) into a real `<h4>` in place.

**References/Bibliography sections are dropped, not fixed.**
`strip_reference_sections()` removes a "References"/"Bibliography" heading
and everything under it, up to the next heading of the same or shallower
level — a long list of author/year/title citations, low value for insight
extraction. Works whether the heading came from trafilatura directly (e.g.
on a report's own "technical-notes" pages) or from the accordion conversion
above (AIHW's own References sections often use the same accordion widget as
everything else) — both look identical by the time extraction reaches
markdown. Applied to every page from either source, not just AIHW.

**Known, accepted limitation: no numeric data behind most AIHW figures.**
Confirmed on real pages, this is fundamentally different depending on how
each chart is embedded:
- **Live Tableau embeds** (`<tableau-viz src="https://viz.aihw.gov.au/...">`)
  — the large majority (93 of 108 chart widgets on the dementia report, 55
  of 76 on the First Nations report). These fetch and render their data
  client-side in a real browser; a plain HTTP fetch never receives the
  underlying numbers at all. Only a static PNG snapshot exists as a print
  fallback, which is a picture, not extractable data.
- **Plain static PNG images** with just a qualitative alt-text description
  (e.g. "Column chart showing that mental & substance use disorders was the
  highest contributor...") and no accompanying data anywhere nearby.
- **A third, genuinely recoverable pattern** (`<div class="c-data-chart">`
  with a `<script data-chart-data type="application/json">` holding the
  actual numbers) exists too — confirmed on 15 of the dementia report's
  chart widgets and 21 of the First Nations report's — but extraction for
  it isn't implemented yet (a deliberate, deferred decision, not an
  oversight - see "Not yet implemented" below).

  In every case, the figure's own heading, its alt-text/screen-reader
  description, and any footnotes are still captured normally - it's
  specifically the underlying numeric data that's unavailable via the two
  unrecoverable patterns.

## 3. ABS extraction

ABS pages needed a fundamentally different approach from AIHW - trafilatura's
single-pass, whole-page extraction repeatedly proved unreliable on ABS's page
structure in ways it never was for AIHW.

**Primary path: a document-order element walker, not trafilatura's own
scoring.** For any URL on the ABS domain, `extract_markdown()` first tries
`extract_abs_article_markdown()` — ported from a teammate's ABS-specific
extractor (`sources/fetch_abs.py`) and adapted into this pipeline. Instead of
handing HTML fragments to trafilatura and hoping its per-fragment scoring
keeps everything, it walks a page's real elements (`h2`-`h6`, `p`, `ul`/`ol`,
`table`, and a chart's own `<pre class="chart-caption">`) directly inside
`<main>`/`<article>`, in document order, and renders each one to markdown
itself — headings, paragraphs and list items as plain text, tables via this
pipeline's own rowspan/colspan-aware renderer (see below) — so there's no
per-fragment heuristic left to silently drop anything. It skips pure
navigation chrome the walker's wider scope exposes that the fallback path
below never saw (Breadcrumb, APA/Citation boxes, an "On this page"
table-of-contents widget whose own list is just empty placeholders) — a
narrow, nav-only list (`ABS_NAV_SECTION_TITLES`), deliberately *not* the
teammate's own script's whole-section exclusions (Methodology/Data
downloads/Footnotes/Media releases), which this pipeline fixed being missing
earlier and keeps. If the walker finds no `<main>`/`<article>` or produces
nothing, `extract_markdown()` falls back to the block-decomposition approach
below, so an ABS page is never worse off than before this walker existed.

AIHW pages never take this branch at all (gated on the ABS domain) and pass
through AIHW's own extraction path completely unaffected (verified
byte-identical before/after every ABS-specific fix in this section).

**Fallback path: field__item block decomposition.** When the walker above
doesn't apply, ABS statistics releases still don't extract cleanly with a
single trafilatura pass the way AIHW pages do:
- Their content is nested multiple levels deep inside `<div
  class="field__item">` wrappers under a `#page-content` container — a
  top-level section's field__item can itself contain several nested
  field__item "paragraph" blocks (a callout, a collapsible sub-section, a
  chart+table pairing, a plain text paragraph, ...), each of which can nest
  further again (confirmed: one section alone had 32 nested field__item
  descendants). trafilatura's main-content scoring picks only *one* nested
  paragraph and silently drops the rest — confirmed on a real "Crisis
  support services" section with two nested paragraphs, "24 hours, 7 days"
  and "COVID-19": only the first survived (duplicated), the second was
  dropped entirely. `_expand_block()` recursively expands every container
  with its own field__item children into those children, all the way down
  to genuine leaves, working around a second trafilatura quirk along the
  way: it treats a bare fragment's first heading as the page title and drops
  it from the body, so each leaf's own heading is pulled out via lxml and
  manually re-added. A container's own framing heading (e.g. "Crisis support
  services" itself) is preserved as its own small leaf ahead of its expanded
  children (`_own_heading()`/`_wrap_heading()`) — dropping it entirely was
  tried first and cost far more than expected, since several levels of
  nesting left many leaves as unlabelled floating text with no indication
  what topic they belonged to. (One separate, narrower pattern - a
  "methodology overview" area wrapping several `<div class="section">` cards
  inside a `<div class="grid">`, with no field__item at all - is handled the
  same way as a fallback within `_expand_block()`.)
- Interactive chart widgets embed raw JSON config (data, palette, headers,
  annotations, axis options) across several `<pre>` tags. trafilatura
  includes `<pre>` content verbatim, so without `_strip_chart_data()` this
  JSON leaks straight into the markdown. The one exception is `<pre
  class="chart-caption">`, which holds a chart's real, human-readable title -
  converted to a `<p class="abs-chart-caption">` instead of being dropped
  with the rest, then extracted directly by `_extract_block()` (the same way
  as tables, below) rather than trusted to trafilatura a second time:
  confirmed a block that was just a caption immediately followed by a large
  table, with no other prose nearby, still got its caption dropped even as a
  plain paragraph. A chart's tab-switcher ("Graph"/"Table") and export
  buttons ("Download table as CSV", ...) are stripped too
  (`_strip_chart_controls()`) - pure UI chrome that was confirmed to crowd
  out a real caption in the one block it happened to sit next to.
- Every `<table>` in a block is extracted independently via
  `_extract_table()`/`_table_to_markdown()` and appended after the prose,
  rather than left for trafilatura to find on its own within the surrounding
  fragment. Confirmed on a real ABS chart: each chart is actually a two-tab
  widget - an empty, JS-only chart mount div plus a genuine data table (the
  chart's accessible alternative, with a real `<caption>` and header cells) -
  and trafilatura's single-pass scoring drops the table when it sees the
  whole tabbed block at once, even though the same table extracts cleanly in
  isolation. Tables without `rowspan`/`colspan` are rendered by this
  pipeline's own `_table_to_markdown()` rather than trafilatura's table
  conversion, which has shown more than one row/column-dropping bug on real
  ABS tables: a cell wrapped in `<p>` silently lost its own text, shifting
  every following column left by one; a plain-text row was dropped outright
  for a cause never fully isolated even after matching its exact HTML
  byte-for-byte in isolation. `_table_to_markdown()` also preserves a
  table's own `<caption>` (e.g. "New South Wales", labelling which state a
  resource table is for) as a bold label above it - previously silently lost
  either way. Tables that *do* use `rowspan`/`colspan` still go through
  trafilatura (this pipeline's own renderer doesn't attempt grid expansion,
  and trafilatura has worked fine on those in practice).
- Some releases keep only a short stub of their methodology inline and link
  out to the real, much longer document under a completely different
  `/methodologies/...` URL — undetectable from the URL shape alone.
  `discover_methodology_page()` finds this via a link literally labelled
  "Methodology" and folds it into the same multi-page combining used for
  AIHW reports (this discovery step runs regardless of which extraction path
  handles each page's actual content).

## 4. Shared extraction details (both sources)

**Last-updated date**, normalized to `YYYY-MM-DD` regardless of source:
`extract_last_updated()` tries `extract_abs_release_date()` first (ABS marks
its real release date as plain text in a `field--label-above` div, not a
`<time>` tag at all — the field name is reused by unrelated "related
articles" cards elsewhere on the page for *their* release date, but those
are marked `field--label-visually_hidden` instead, which is what tells the
page's own date apart from theirs), then falls back to AIHW's `<time>`-tag
classes, then any single unambiguous `<time datetime>` (multiple candidates
are left as unknown rather than guessing — unrelated `<time>` tags can share
an identical generic class like `class="datetime"`, so counting distinct
tags rather than distinct class names matters here), then a text-based
fallback. This replaced an earlier version that could silently return a
wrong date entirely (it picked up a `<time>` tag belonging to an unrelated
"related articles" card) or `unknown` for pages with no `<time>` markup even
though a real date was present as plain text.

**Data-file links.** Each page is checked for links to downloadable data
files — `.xlsx`/`.xls`/`.csv`/`.zip` (`extract_data_links()`, not
downloaded, just recorded).

**Boilerplate line stripping.** `strip_boilerplate()` drops a couple of
orphaned in-page-nav labels (`**On this page:**`, a mangled `### On this
page In this section` heading) that trafilatura leaves behind after
stripping their link list — matched as whole lines only, never a substring,
since near-identical real prose (e.g. "On this page, ... refers to...") must
survive untouched.

## 5. Saving

One `.md` file per report/URL under `source-extracted-files/<AIHW|ABS>/`,
named from a slugified title (lowercased, non-alphanumeric -> `-`, capped at
60 chars) plus an 8-character hash of the canonical URL (e.g.
`dementia-in-australia-8f2cfd2c.md`) — the hash is what actually guarantees
uniqueness, since two different reports can easily share a generic title
like "Summary" and would otherwise silently overwrite each other's file.
It's stable across runs for the same URL, so re-fetching a report always
rewrites the same file.

Frontmatter: `source`, `url` (canonical, post-redirect), `title`,
`extracted_at` (UTC ISO timestamp), `content_hash` (SHA-256 of the combined
body), `last_updated`, `page_count` + `pages` (every section/companion-page
URL combined into this file, each with its own `last_updated` and
`content_hash`), `data_link_count` + `data_links`.

## 6. Change detection and skip-if-cached

**`manifest.json`, down to the section.** Every report's `content_hash`,
title, saved file path, and `first_seen_at`/`last_seen_at`/`last_changed_at`
timestamps are tracked in `source-extracted-files/manifest.json`, keyed by
the canonical URL (after redirects) so different entry points into the same
report — e.g. with or without a trailing `/contents/about` — share one entry
instead of fragmenting into two. Console output flags each save as `CHANGED`
or `unchanged` based on a SHA-256 comparison against the previous run, not
on the URL or raw HTML (AIHW reshuffles page layout without changing
content). Each entry also nests a `pages` map — one content hash,
last-updated date, and `last_changed_at` per section/page URL — so
`record_content()` can report *which* specific sections changed (e.g.
"CHANGED (1/37 sections changed)") instead of only "something in this report
changed"; a brand-new report or a page with no prior history reports as
unchanged at the page level rather than a false "everything changed" burst.
The same per-page detail is written into each `.md` file's own `pages:`
frontmatter, not just the manifest.

**Skip-if-cached.** By default, a URL that's already in the manifest with
its `.md` file still on disk is skipped after one cheap request — the full
per-section re-fetch only happens for new URLs, or when you answer "y" to
the "re-check already-extracted URLs?" prompt at startup. This is what keeps
repeat runs on the same URLs fast (a full 80+ section AIHW report only gets
fully re-fetched when you actually ask for a refresh).

## 7. Robustness fixes from a full-script review

`fetch_and_extract()` accepts an already-fetched `html`/`final_url` so a
report's entry page is fetched once, not twice (once for the cache check,
once inside extraction, as it did before). Each page's HTML is parsed by
`lxml` once and the tree is shared across `extract_markdown()`,
`extract_last_updated()`, and `discover_methodology_page()`, instead of each
re-parsing the same string. `extract_markdown()`'s ABS fallback path uses
the block-based decomposition for *any* number of "field__item" blocks found
(including just one), rather than only 2+ — a short single-block ABS page
used to fall back to a whole-page trafilatura pass, the exact "picks one
region, drops the rest" behavior this whole approach exists to avoid.
`process_source()` waits `REQUEST_DELAY` between distinct top-level URLs
too, not just between sections within one report. `load_manifest()`
recovers from a corrupted/truncated `manifest.json` (starts fresh with a
warning) instead of crashing the whole run, and a disk-write failure in
`save_markdown()`/`save_manifest()` is now caught and reported like a fetch
failure rather than stopping the batch.

## What this deliberately does NOT do

- Methodology-page detection is one specific, verified pattern (a link
  literally labelled "Methodology" under `/methodologies/...`), not a
  general "find every companion page" solution — other possible split-out
  content (e.g. a separate "Explanatory notes" or "Quality declaration"
  page) isn't checked for.
- No PDF handling — a URL ending in `.pdf` isn't given special treatment;
  trafilatura only understands HTML.
- No archive-on-change — an updated report overwrites the previous `.md`
  file in place rather than keeping a superseded copy.
- No automated tests — every fix above was verified with one-off manual
  live-fetch scripts during development, not a committed test suite, so
  there's no regression safety net for future changes.
- Not wired into `src/common/fetch.py` / `src/common/extract.py` in the
  main repo — this duplicates that logic standalone for a quick demo, not
  the production integration.
- No LLM step — this only produces the raw `.md` files that get handed off
  to the LLM team afterward.

### Not yet implemented (known, deferred opportunity)

- **AIHW's `c-data-chart` JSON widgets.** Confirmed a genuine, recoverable
  data source distinct from the Tableau/PNG limitation above — real numbers
  sitting in a `<script data-chart-data type="application/json">` tag,
  already present in the fetched HTML. Confirmed on 15 of the dementia
  report's chart widgets (9 of 81 pages) and 21 of the First Nations
  report's (5 of 37 pages) — a meaningful minority (roughly 1 in 7 and
  1 in 4 of each report's charts respectively), not a full fix for every
  figure. A related bug was also found alongside it: the heading
  immediately before one such chart was silently dropped by trafilatura,
  likely because the large inline JSON script right after it throws off
  trafilatura's scoring for that block — every other heading on the same
  page was unaffected. Deliberately not implemented yet — a decision to
  revisit later, not an oversight.

## Setup

```
pip install -r requirements.txt
```

## Running it

```
python collect_and_extract.py
```

You'll be prompted for AIHW-1 and AIHW-2 (mandatory), then asked "Do you
have more URLs? (y/n)" in a loop for AIHW-3, AIHW-4, ... Once you answer
"n", the same prompt sequence repeats for ABS. A URL that doesn't match the
expected agency domain is rejected on the spot and re-prompted.

Once both lists are collected, you're asked once: "Re-check
already-extracted URLs for content updates? (y/n)". Answer "n" (or just
press Enter) for a fast run that skips anything already in the manifest
with its file still on disk; answer "y" to force a full re-fetch of
everything, e.g. when you actually want to check AIHW/ABS for updates.

Each URL is then fetched, extracted, and saved — failures print a "Skipped"
line and the run continues. A multi-page AIHW report or an ABS release with
a separate methodology page prints how many sections/pages it combined;
every save prints `CHANGED` or `unchanged` plus its last-updated date and
data-file count.

## Files

| File | Purpose |
|---|---|
| `collect_and_extract.py` | The whole pipeline: collect URLs -> fetch -> extract -> save |
| `requirements.txt` | `requests`, `trafilatura`, `lxml`, `beautifulsoup4` |
| `source-extracted-files/AIHW/*.md` | Extracted AIHW reports (created at runtime) |
| `source-extracted-files/ABS/*.md` | Extracted ABS articles (created at runtime) |
| `source-extracted-files/manifest.json` | Change-detection + skip-if-cached state (created at runtime) |
| `sources/fetch_abs.py` | A teammate's separate, standalone ABS extractor - the document-order-walking technique it introduced was ported into this pipeline's own ABS extraction path (see above); this file itself isn't run by `collect_and_extract.py` |

## A note for the LLM team: what the frontmatter is for

Every `.md` file starts with a YAML frontmatter block (between the two `---`
lines) before the actual extracted content. It exists for **this pipeline's
own bookkeeping** — change detection, skip-if-cached, future data-table
lookups — not as input for insight extraction. Most of it has no reasoning
value and is safe (and recommended) to strip before it goes into an LLM
prompt:

| Field | What it's for | Useful to feed the LLM? |
|---|---|---|
| `content_hash` | This pipeline's own `manifest.json` change detection | No — meaningless outside this repo |
| `page_count`, `pages:` (nested `url`/`content_hash`/`last_updated` per section) | Skip-if-cached + per-section change tracking (`record_content()` in `collect_and_extract.py`), so a change in one section of an 81-section report can be pinpointed instead of just "something changed" | No — pure bookkeeping, and it's the single biggest contributor to frontmatter size |
| `data_link_count`, `data_links:` | Pointers to the underlying `.xlsx`/`.csv`/`.zip` data tables (not downloaded by this script — noted for whichever later phase actually parses the numeric tables) | No, not for text-insight extraction — but don't discard these, a later phase will want them |
| `extracted_at` | This pipeline's own audit trail | Marginal |
| `source`, `url`, `title` | Provenance/citation — which agency, which page | **Yes** — worth keeping for citing findings back to a source |
| `last_updated` | How current the underlying statistics are | **Yes** — useful context for caveating findings |

**Measured overhead** (frontmatter as a share of total file size, across the
files this script has actually produced): 1.3%–6.3%, i.e. roughly
450–10,500 characters per file. The large end is almost entirely the
`pages:` list on multi-section AIHW/ABS reports (37–81 entries, each with a
URL + hash + date) — that's pure pipeline metadata, not content, and costs
real prompt tokens for zero reasoning value if sent through as-is.

**Suggested handling on your side:** don't send the frontmatter block
through to the model. Split each file on the closing `---` line, keep the
body as the actual LLM input, and if you want provenance/freshness in the
prompt, re-inject just `title` + `source url` + `last_updated` as a couple
of short lines rather than the raw YAML — that gets the two fields worth
paying tokens for without the hash/URL lists that only this pipeline needs.

Each combined section in the body also carries its own inline `Source:
<url>` line — kept deliberately, even though the same URLs already live in
`pages:` above, in case your pipeline chunks these documents for
embedding/retrieval: a chunk pulled out on its own later won't carry the
frontmatter with it, so this is what keeps a specific paragraph traceable
back to its exact source page.
