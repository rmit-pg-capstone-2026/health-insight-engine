# Manual health engine sandbox

A standalone, disposable proof-of-concept. It is **not** connected to any
team repo, git history, or shared codebase — it exists purely to demo one
thing on my own machine before handing off to the LLM team.

## What this proves

That a minimal, fully manual URL-in -> Markdown-out pipeline works end to
end for two sources (AIHW and ABS), without any of the discovery/dedup
machinery from the other sandboxes:

1. **Two-phase design: collect URLs first, extract second.** Nothing hits
   the network while URLs are being typed — `collect_urls()` just gathers
   them into plain lists (mandatory URL 1 and 2, then a "do you have more?"
   loop), matching the original sketch. Input mistakes stay cheap because
   fetching only starts once both source's lists are confirmed. Each URL is
   checked against the expected agency domain (`aihw.gov.au` / `abs.gov.au`,
   including subdomains) as it's typed — a wrong-source or malformed URL is
   rejected and re-prompted (mandatory slots) or dropped with a warning
   (optional slots), before any network request is made.
2. **Fetching.** Plain `requests.get()` with a custom User-Agent and a 20s
   timeout, wrapped in a `FetchError` if the request fails or returns a bad
   status. A failed URL is skipped, not retried, so one bad URL doesn't kill
   the whole batch.
3. **Multi-page AIHW reports.** AIHW publishes long reports as many pages
   under a shared `.../contents/<section>` path (a sidebar table of
   contents), not as HTTP pagination. `discover_report_pages()` detects this
   shape and pulls every sibling section link from the table of contents;
   `fetch_and_extract()` fetches all of them (politely, with a delay between
   requests, capped at `MAX_REPORT_PAGES`) and stitches them into one
   combined markdown document, so giving it any single section URL (e.g. the
   "About" page) captures the whole report, not just that one section.
4. **ABS's fragmented page structure.** ABS statistics releases don't extract
   cleanly with a single trafilatura pass the way AIHW pages do:
   - Their content is split into many separate `<div class="field__item">`
     blocks under a `#page-content` container. trafilatura's main-content
     scoring picks only *one* of those blocks (usually just the intro
     paragraph) and silently drops the rest — even when handed only that
     container's HTML in isolation. `extract_markdown()` detects this shape
     and extracts + combines every block separately instead
     (`_extract_block()`), working around a second trafilatura quirk along
     the way: it treats a bare fragment's first heading as the page title
     and drops it from the body, so each block's own heading is pulled out
     via lxml and manually re-added.
   - Interactive chart widgets on these pages embed raw JSON config (data,
     palette, captions, axis options) across several `<pre>` tags.
     trafilatura includes `<pre>` content verbatim, so without
     `_strip_chart_data()` this JSON leaks straight into the markdown.
   - Some releases keep only a short stub of their methodology inline and
     link out to the real, much longer document under a completely
     different `/methodologies/...` URL — undetectable from the URL shape
     alone. `discover_methodology_page()` finds this via a link literally
     labelled "Methodology" and folds it into the same multi-page combining
     used for AIHW reports.

   AIHW pages have none of this structure and pass through the single-pass
   path unaffected (verified byte-identical before/after each of these
   fixes).
5. **Extraction (trafilatura).** `trafilatura.extract(html,
   output_format="markdown", include_tables=True)` converts raw HTML
   straight to Markdown (no intermediate `.txt` step, so headings/lists/
   tables survive), and `trafilatura.extract_metadata(html)` pulls the page
   title (falling back to the raw URL if none is found). Each page is also
   checked for links to downloadable data files — `.xlsx`/`.xls`/`.csv`/
   `.zip` (`extract_data_links()`, not downloaded, just recorded).
   `strip_boilerplate()` then drops a couple of orphaned in-page-nav labels
   (`**On this page:**`, a mangled `### On this page In this section`
   heading) that trafilatura leaves behind after stripping their link list —
   matched as whole lines only, never a substring, since near-identical real
   prose (e.g. "On this page, ... refers to...") must survive untouched.
   `extract_last_updated()` finds each page's date, normalized to
   `YYYY-MM-DD` regardless of source: it tries `extract_abs_release_date()`
   first (ABS marks its real release date as plain text in a
   `field--label-above` div, not a `<time>` tag at all - the field name is
   reused by unrelated "related articles" cards elsewhere on the page for
   *their* release date, but those are marked `field--label-visually_hidden`
   instead, which is what tells the page's own date apart from theirs), then
   falls back to AIHW's `<time>`-tag classes, then any single unambiguous
   `<time datetime>` (multiple candidates are left as unknown rather than
   guessing - unrelated `<time>` tags can share an identical generic class
   like `class="datetime"`, so counting distinct tags rather than distinct
   class names matters here), then a text-based fallback. This replaced an
   earlier version that could silently return a wrong date entirely (it
   picked up a `<time>` tag belonging to an unrelated "related articles"
   card) or `unknown` for pages with no `<time>` markup even though a real
   date was present as plain text.
6. **Saving.** One `.md` file per report/URL under
   `source-extracted-files/<AIHW|ABS>/`, named from a slugified title
   (lowercased, non-alphanumeric -> `-`, capped at 60 chars) plus an
   8-character hash of the canonical URL (e.g. `dementia-in-australia-
   8f2cfd2c.md`) - the hash is what actually guarantees uniqueness, since
   two different reports can easily share a generic title like "Summary"
   and would otherwise silently overwrite each other's file. It's stable
   across runs for the same URL, so re-fetching a report always rewrites
   the same file. Frontmatter: `source`, `url` (canonical, post-redirect),
   `title`, `extracted_at` (UTC ISO timestamp), `content_hash` (SHA-256 of
   the combined body), `last_updated`, `page_count` + `pages` (every
   section/companion-page URL combined into this file), `data_link_count` +
   `data_links`.
7. **Change detection (`manifest.json`), down to the section.** Every
   report's `content_hash`, title, saved file path, and `first_seen_at`/
   `last_seen_at`/`last_changed_at` timestamps are tracked in
   `source-extracted-files/manifest.json`, keyed by the canonical URL (after
   redirects) so different entry points into the same report — e.g. with or
   without a trailing `/contents/about` — share one entry instead of
   fragmenting into two. Console output flags each save as `CHANGED` or
   `unchanged` based on a SHA-256 comparison against the previous run, not
   on the URL or raw HTML (AIHW reshuffles page layout without changing
   content). Each entry also nests a `pages` map — one content hash,
   last-updated date, and `last_changed_at` per section/page URL — so
   `record_content()` can report *which* specific sections changed (e.g.
   "CHANGED (1/37 sections changed)") instead of only "something in this
   report changed"; a brand-new report or a page with no prior history
   reports as unchanged at the page level rather than a false "everything
   changed" burst. The same per-page detail is written into each `.md`
   file's own `pages:` frontmatter, not just the manifest.
8. **Skip-if-cached.** By default, a URL that's already in the manifest with
   its `.md` file still on disk is skipped after one cheap request — the
   full per-section re-fetch only happens for new URLs, or when you answer
   "y" to the "re-check already-extracted URLs?" prompt at startup. This is
   what keeps repeat runs on the same URLs fast (a full 80+ section AIHW
   report only gets fully re-fetched when you actually ask for a refresh).
9. **Robustness fixes from a full-script review.** `fetch_and_extract()`
   accepts an already-fetched `html`/`final_url` so a report's entry page is
   fetched once, not twice (once for the cache check, once inside
   extraction, as it did before). Each page's HTML is parsed by `lxml` once
   and the tree is shared across `extract_markdown()`,
   `extract_last_updated()`, and `discover_methodology_page()`, instead of
   each re-parsing the same string. `extract_markdown()` now uses the
   block-based path for *any* number of "field__item" blocks found
   (including just one), rather than only 2+ - a short single-block ABS page
   used to fall back to the whole-page trafilatura pass, the exact "picks
   one region, drops the rest" behavior this whole section exists to avoid.
   `process_source()` waits `REQUEST_DELAY` between distinct top-level URLs
   too, not just between sections within one report. `load_manifest()`
   recovers from a corrupted/
   truncated `manifest.json` (starts fresh with a warning) instead of
   crashing the whole run, and a disk-write failure in `save_markdown()`/
   `save_manifest()` is now caught and reported like a fetch failure rather
   than stopping the batch.

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

## Setup

```
pip install -r requirements.txt
```

## Running it

```
python collect_and_extract.py
```

You'll be prompted for AIHW-1 and AIHW-2 (mandatory), then asked
"Do you have more URLs? (y/n)" in a loop for AIHW-3, AIHW-4, ... Once you
answer "n", the same prompt sequence repeats for ABS. A URL that doesn't
match the expected agency domain is rejected on the spot and re-prompted.

Once both lists are collected, you're asked once: "Re-check
already-extracted URLs for content updates? (y/n)". Answer "n" (or just
press Enter) for a fast run that skips anything already in the manifest
with its file still on disk; answer "y" to force a full re-fetch of
everything, e.g. when you actually want to check AIHW/ABS for updates.

Each URL is then fetched, extracted, and saved — failures print a
"Skipped" line and the run continues. A multi-page AIHW report or an ABS
release with a separate methodology page prints how many sections/pages it
combined; every save prints `CHANGED` or `unchanged` plus its last-updated
date and data-file count.

## Files

| File | Purpose |
|---|---|
| `collect_and_extract.py` | The whole pipeline: collect URLs -> fetch -> extract -> save |
| `requirements.txt` | `requests`, `trafilatura`, `lxml` |
| `source-extracted-files/AIHW/*.md` | Extracted AIHW reports (created at runtime) |
| `source-extracted-files/ABS/*.md` | Extracted ABS articles (created at runtime) |
| `source-extracted-files/manifest.json` | Change-detection + skip-if-cached state (created at runtime) |

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
