# Layer 1 — Collect and Extract

This folder is **Layer 1** of the Health Insight Engine. Its job is to find
Australian health publications from two government agencies, download them,
and turn each one into a clean Markdown file that the next layer (insight
extraction, an LLM) can read.

- **AIHW** — Australian Institute of Health and Welfare (`aihw.gov.au`).
  Long reports such as "Dementia in Australia".
- **ABS** — Australian Bureau of Statistics (`abs.gov.au`). Statistical
  releases and shorter articles.

If you are new to the project, read sections 1 to 3 first. They explain what
this layer does and how it fits the rest of the system. The later sections go
into detail.

---

## Contents

1. [Workflow at a glance](#1-workflow-at-a-glance)
2. [Where this layer sits in the whole pipeline](#2-where-this-layer-sits-in-the-whole-pipeline)
3. [Skeleton of this layer](#3-skeleton-of-this-layer)
4. [Step 1 — Finding pages](#4-step-1--finding-pages)
5. [Step 2 — Fetching and extracting a page](#5-step-2--fetching-and-extracting-a-page)
6. [Step 3 — Change detection and versioning](#6-step-3--change-detection-and-versioning)
7. [What this layer produces](#7-what-this-layer-produces)
8. [Running it](#8-running-it)
9. [Problems we solved and why the code looks the way it does](#9-problems-we-solved-and-why-the-code-looks-the-way-it-does)
10. [Standalone mode (earlier versions)](#10-standalone-mode-earlier-versions)
11. [Known limitations — scope of this release](#11-known-limitations--scope-of-this-release)

---

## 1. Workflow at a glance

### The whole job, in one picture

```
   AIHW website                          ABS website
 (report search API)          (articles listing)   (release calendar)
        │                            │                    │
        ▼                            ▼                    ▼
 discover_aihw.py        discover_abs_articles.py   discover_abs_statistics.py
        │                            │                    │
        └──────────────┬─────────────┴────────────────────┘
                       ▼
              pipeline/discover.py
      "pages dated in the last 14 days" + filters
      (skip hub pages, skip unrelated AIHW topics)
                       │
                       │      pipeline/sources.json
                       │      (manual extra pages, checked every run)
                       ▼                │
                 list of page URLs ◄────┘
                       │
                       ▼   for each URL (one at a time)
        ┌─────────────────────────────────────────┐
        │  fetch_and_extract()                    │
        │                                         │
        │  1. fetch the page                      │
        │  2. find the rest of the report         │
        │     (AIHW sections, ABS methodology     │
        │      page, AIHW hub cards)              │
        │  3. extract each page to Markdown       │
        │     (AIHW and ABS use different logic)  │
        │  4. clean it (nav, charts, references)  │
        │  5. join the sections into one document │
        └───────────────────┬─────────────────────┘
                            ▼
              SHA-256 hash of the document text
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
   hash already known?             hash is new
   → "unchanged", save nothing     → save a versioned .md file
                                   → add a row to `documents`
                                     (status = new)
                                           │
                                           ▼
                          Layer 2 reads documents with status "new"
```

### How a single page is processed

```
 URL ──► fetch ──► is it an AIHW multi-page report? ──yes──► fetch every section
                │                                             in its sidebar
                ├──► ABS page with a "Methodology" link? ──yes──► also fetch that page
                ├──► AIHW hub page with link cards? ──────yes──► also fetch each card's page
                ▼
        for every page fetched:
          ABS  → walk the page's real elements in order, convert each one
          AIHW → fix collapsible sections, split into content blocks,
                 convert each block
          then → strip nav / chart data / references / auto citation line
        ▼
   sections joined with "## <title>" and "Source: <url>" lines
        ▼
   one Markdown document + YAML header (title, url, last updated, hashes)
```

---

## 2. Where this layer sits in the whole pipeline

The project turns public ABS and AIHW health publications into a prioritised
briefing (PDF) for a private health insurer. It has four layers. Each layer
reads what the previous one saved and writes its own output.

```
 ┌──────────────────────┐   ┌─────────────────────┐   ┌───────────────────────┐   ┌─────────────────┐
 │ 1. collect_and_      │   │ 2. insight-         │   │ 3. priority_          │   │ 4. briefing/    │
 │    extract/          │──►│    extraction-test/ │──►│    assessment/        │──►│                 │
 │ (THIS LAYER)         │   │                     │   │                       │   │                 │
 │ web pages → Markdown │   │ LLM finds up to 10  │   │ LLM rates relevance   │   │ renders the     │
 │ files                │   │ insights per        │   │ and priority of each  │   │ PDF briefing    │
 │ (no LLM here)        │   │ document, with      │   │ insight               │   │ and emails it   │
 │                      │   │ verbatim quotes     │   │                       │   │                 │
 └──────────────────────┘   └─────────────────────┘   └───────────────────────┘   └─────────────────┘
```

**What this layer hands to Layer 2:** one Markdown file per page version, plus
a row in the `documents` table pointing at that file. Layer 2 quotes text
directly from these files, and every quote is checked against the file
afterwards. That is why this layer works so hard to produce **complete** and
**clean** text. Content lost here can never become an insight, and noise left
in here can end up inside a quote.

### How it runs in the deployed system

```
 Step Functions (weekly)
   └─ "Collect" state
        └─ AWS Lambda  health-insight-pipeline   event: {"stage": "collect"}
             └─ pipeline/lambda_handler.py
                  └─ pipeline/run.py  → run_collect()
                       ├─ pipeline/discover.py       finds the page URLs
                       ├─ pipeline/stages.py         collect(): calls this folder's
                       │                             fetch_and_extract() and save_markdown()
                       ├─ pipeline/db.py             SQLite: sources, documents
                       └─ pipeline/storage.py        /tmp/data on Lambda, synced with S3
```

The same code runs on a laptop with `python pipeline/run.py collect`. When no
S3 bucket is configured, everything stays in the local `data/` folder.

---

## 3. Skeleton of this layer

### Files in this folder

```
collect_and_extract/
├── collect_and_extract.py     the extraction engine (used by the deployed pipeline)
├── discover_aihw.py           finder: AIHW report search API
├── discover_abs_articles.py   finder: ABS health articles listing
├── discover_abs_statistics.py finder: ABS release calendar (health statistics)
├── discover_and_run.py        standalone runner with its own state file (see section 10)
├── requirements.txt           Python packages for this folder on its own
└── README.md                  this file
```

| File | What it does |
|---|---|
| `collect_and_extract.py` | The engine. Fetches a URL, finds the other pages of the same report, converts HTML to clean Markdown (separate logic for AIHW and ABS), hashes the result and saves a versioned `.md` file. It also contains the original interactive prompt flow (`main()`), which the deployed pipeline does not use. |
| `discover_aihw.py` | Asks AIHW's own report-search API for every report released after a given date. Returns title, URL, release date, type and topic. |
| `discover_abs_articles.py` | Reads ABS's server-rendered Health "related articles" listing page by page and returns articles released after a given date. |
| `discover_abs_statistics.py` | Reads ABS's site-wide release calendar and keeps only rows under `/statistics/health/`. |
| `discover_and_run.py` | A self-contained runner for this folder. It uses a `manifest.json` file for state, remembers a "since" date per finder and re-checks old pages in small batches. It is **not** part of the deployed flow. |
| `requirements.txt` | `requests`, `trafilatura`, `lxml`, `beautifulsoup4`. The whole project is installed from the root `requirements.txt`, which also adds `lxml_html_clean`. |

### Main parts inside `collect_and_extract.py`

| Group | Functions | Purpose |
|---|---|---|
| Fetching | `fetch_html`, `_fetch_page_with_retry` | Download a page (20 s timeout). Sub-pages get 3 attempts. |
| Finding the rest of a report | `discover_report_pages`, `discover_methodology_page`, `discover_hub_card_pages` | AIHW sidebar sections, the ABS methodology page, AIHW hub cards. |
| Orchestration | `fetch_and_extract` | Runs the whole page → document process and returns an `ExtractResult`. |
| Choosing a strategy | `extract_markdown` | Picks the extraction path for the page template. |
| ABS extraction | `extract_abs_article_markdown`, `_extract_abs_content_blocks` | Walk the page's real elements in document order. |
| AIHW extraction | `_convert_aihw_accordions`, `_expand_block`, `_expand_widget`, `_split_by_headings`, `_extract_block` | Fix collapsible sections, split nested content into leaf blocks, convert each block. |
| Tables, lists, captions | `_extract_table`, `_table_to_markdown`, `_list_to_markdown` | Our own converters, because the library dropped cells and rows. |
| Cleanup | `_strip_chart_data`, `_strip_chart_controls`, `_strip_nav_elements`, `_strip_downloadable_resources`, `strip_boilerplate`, `strip_reference_sections` | Remove everything that is not report content. |
| Metadata | `extract_last_updated`, `extract_abs_release_date`, `extract_data_links` | Last-updated date and links to downloadable data files. |
| Saving | `save_markdown` | Write the `.md` file with a YAML header. |
| Standalone-only | `record_content`, `process_source`, `save_current_copy`, `load_manifest`, `save_manifest`, `main` | Manifest bookkeeping and the interactive prompt (section 10). |

### The pieces outside this folder that this layer plugs into

| File | Role for this layer |
|---|---|
| `pipeline/discover.py` | Calls the three finders, applies the date window and the skip filters. |
| `pipeline/collect_settings.json` | The window length and skip rules (section 4). |
| `pipeline/sources.json` | Manually listed pages that are checked on every run. |
| `pipeline/stages.py` → `collect()` | Calls `fetch_html`, `fetch_and_extract` and `save_markdown` for one page. |
| `pipeline/run.py` → `run_collect()` | Loops over the pages, decides new / changed / unchanged and writes the database rows. |
| `pipeline/db.py` | The `sources` and `documents` tables. |
| `pipeline/storage.py` | Local folder and S3 file syncing. |
| `pipeline/lambda_handler.py` and `stepfunctions/weekly.asl.json` | Run the collect stage on AWS every week. |

---

## 4. Step 1 — Finding pages

Three finders each ask a different part of the agencies' websites "what has
been published since this date?". They are independent. If one fails (site
down, page layout changed), it is reported and skipped, and the other two
still run.

| Finder | Where it looks | How it works |
|---|---|---|
| `discover_aihw.py` | AIHW's internal report-search API (`/api/search/reports`) | Sends the same request AIHW's own search box sends, with browser-like headers because the API sits behind Cloudflare. Excludes reports hosted outside `aihw.gov.au`. |
| `discover_abs_articles.py` | `abs.gov.au/statistics/health/related-articles` | Reads the listing's rows. This page is already limited to the Health topic. The general `/articles` page is not used, because its Health filter runs in JavaScript and a plain request returns every topic. |
| `discover_abs_statistics.py` | `abs.gov.au/release-calendar/latest-releases` | The calendar covers all ABS topics and has no topic filter. Rows are kept only if the link starts with `/statistics/health/`, which also removes media-release rows. |

**Paging rule used by all three:** results are only roughly newest-first, so
the finders look at every item on a page and stop only when a whole page has
nothing newer than the cut-off date. They do not stop at the first old item.

### How the deployed pipeline uses the finders

`pipeline/discover.py` calls each finder with a cut-off date of
**today minus `discovery_days`** (14 by default). The window is deliberately
wider than the weekly schedule, so a missed run loses nothing. It then
applies these filters from `pipeline/collect_settings.json`:

| Setting | Default | Effect |
|---|---|---|
| `discovery_days` | 14 | How far back the finders look on every run. |
| `skip_hub_pages` | true | Skips AIHW landing pages one level deep, such as `/mental-health`. They merge many sub-pages into one document and their date changes whenever anything under them changes. |
| `aihw_skip_topics` | housing, child protection, youth justice, adoptions, homelessness services, housing assistance, corporate publications, Australia's welfare | AIHW topics unrelated to health care. Matched on the topic in the address. |

ABS finders need no topic filter, as they are already health-only.

`pipeline/sources.json` is a manual list of extra pages (older reports, or
pages the finders never surface). They are fetched on every run alongside the
discovered ones. Each entry is `{"agency": "AIHW" | "ABS", "url": "..."}`.

**What happens next, per page:**

- A page that has never been seen becomes a new document.
- A page seen before becomes a new document only if its content changed.
- A page that fails to load is recorded with its error and retried next run.
  It does not stop the other pages.

---

## 5. Step 2 — Fetching and extracting a page

This is where most of the work in this layer is. A government web page is
mostly not the report: it has menus, cookie banners, download buttons, chart
controls, related-article widgets and reference lists. The goal is to keep
only the real content, as Markdown.

### 5.1 Expanding to the whole report

One URL is often only part of a report, so `fetch_and_extract()` gathers the
other parts first:

| Situation | What the code does |
|---|---|
| **AIHW long report** — pages live under `…/contents/<section>` | Reads the sidebar table of contents and fetches every section (up to 150). |
| **ABS release** with a separate methodology page | Follows the link labelled "Methodology" (only if it goes to a `/methodologies/` page on the same site) and appends that page. The inline "Methodology" section on ABS pages is often just a short stub. |
| **AIHW hub / landing page** with link cards | Follows every link inside every card (same site only) and merges those pages in. |
| **Anything else** | Just the one page. |

Each extra page is fetched with up to 3 attempts. Pages that still fail are
listed as `missing_pages` (see section 6). Pages are fetched one at a time
with a 0.3 second pause between requests.

### 5.2 Why AIHW and ABS need different extraction

A general "turn this HTML into Markdown" library (trafilatura) works on many
AIHW pages. On ABS pages, and on several AIHW templates, it silently throws
away content: it scores page fragments and keeps the best one. We found
whole sections disappearing with no sign in the output. So the code avoids
that scoring step wherever it caused loss.

**ABS pages**

1. A document-order walker visits every heading, paragraph, list, table and
   chart caption on the page, in the order they appear, and converts each
   one directly. Nothing is left to a scoring step.
2. It skips navigation sections ("breadcrumb", "APA", "citation", "ABS main
   menu", "on this page") and a list of known button labels ("Download table
   as CSV", "Share this page", "Back to top", and so on).
3. Methodology, data download and footnote sections are **kept**.
4. If the walker finds nothing, the page falls back to the general path
   below, so it is never worse off.

**AIHW pages** have several templates. The code detects which one it has:

| Template | How it is recognised | What the code does |
|---|---|---|
| Long report | An element with id `page-content` | Expands nested `field__item` wrappers down to the lowest-level content blocks and extracts each separately, keeping each block's own heading. |
| Short web article | A `l-web-article__content` container | Expands nested `widget` blocks the same way. A widget holding several headings is split into one piece per heading. |
| Hub / microsite page | Widgets inside `<main>` | Same widget expansion. |
| Anything else | None of the above | One extraction pass over `<main>`. |

**Fixes applied to AIHW pages before extraction**

- Collapsible sections: their titles are buttons, not headings, so the code
  turns each button into a real heading. Without this, unrelated topics merged
  into one block. "References" and "Bibliography" accordions are removed.
- Chart data (`<pre>` JSON) is removed. A chart's caption is kept, because
  it describes what the chart shows.
- Chart tab switchers and "download" button rows are removed.
- `<nav>` elements are removed, since they only hold navigation.
- AIHW's downloadable-data tab is removed from the text (its links are
  recorded separately, see 5.4).

### 5.3 Converting the pieces

- **Tables** are rendered by our own converter, which keeps every row and
  cell and the table caption. The library had dropped cells and shifted
  columns. Tables with merged cells (`rowspan`/`colspan`) are handed to the
  library, which handles those correctly.
- **Lists and chart captions** are pulled out and rendered separately, for the
  same reason (the library dropped a whole bullet list from a block).
- Each block keeps its own heading.

**Clean-up after conversion**

- Orphan navigation labels ("On this page", "In this section", "Go back to
  top", "Feedback") are removed, matching whole lines only.
- Sections titled **References**, **Bibliography** or **Citation** are
  removed, up to the next heading of the same or higher level.
- The auto-generated line `accessed <day> <month> <year>.` is removed. It
  holds the date the pipeline ran, not anything the source says, so keeping it
  would make a page look changed every day (section 9, problem 3).

When a report has several pages, the sections are joined like this, so a
piece of text stays traceable to its page even on its own:

```
## <page title>

Source: <page url>

<page content>

---

## <next page title>
...
```

### 5.4 Extra information collected

| Item | How it is found |
|---|---|
| **Last updated date** (YYYY-MM-DD) | Tried in order: ABS release-date field → AIHW footer "last updated" tag → report title date tag → a single other date tag → "Last updated" text. |
| **Data file links** (`.xlsx`, `.xls`, `.csv`, `.zip`) | ABS: found directly in the HTML. AIHW: the Data tab is filled in by JavaScript, so the code sends the same request that tab sends to AIHW's API and reads the links from the answer. The files are **recorded, not downloaded**. |
| **Title** | From the page metadata. For a multi-page report, a trailing "About" or "Summary" is removed. |

---

## 6. Step 3 — Change detection and versioning

**Purpose:** never lose the exact text an insight was quoted from, even if
the agency later edits the page, and never treat a cosmetic change as a real
one.

1. The final document text (the Markdown body, **not** the YAML header) is
   hashed with SHA-256.
2. The hash is compared with the hashes already stored for that page.
3. **Same hash** → `unchanged`. Nothing is saved.
4. **New hash** → a new file is saved and a new row is added to `documents`
   with status `new`. The old file stays where it is.
5. If an older version of the same page is still waiting to be processed by
   Layer 2 (status `new`), it is marked `superseded` and skipped, so no
   effort goes into text that is already out of date.

**File names** include the title, a hash of the URL and a hash of the
content:

```
abs-national-health-survey-2022-ec4e2569-a91c3e2b.md
│   └──── title (max 60 chars) ────┘ └ URL ┘ └ content ┘
└ agency
```

- The **URL hash** stops two pages with the same generic title (for example
  "Summary") from overwriting each other.
- The **content hash** gives every version its own file. A version file is
  never overwritten or deleted.

**Incomplete captures.** If some sub-pages of a multi-page report did not
load even after retrying, the result is incomplete.

- For a page already stored, the new capture is **not** saved. The existing
  version is kept and the page is retried next run. Otherwise a truncated
  copy would look like a real change.
- For a page never seen before, the partial capture is saved anyway (partial
  is better than nothing), and the number of missing pages is reported.

**What the collect step records in the database**

| Table | Collect-stage fields |
|---|---|
| `sources` | `url`, `agency`, `origin` (`manual` or `discovered`), `topic`, `title`, `release_date` (from the finder), `last_checked_at`, `last_error` |
| `documents` | `source_id`, `content_hash`, `fetched_at`, `title`, `markdown_path` (relative to the data folder, also the S3 key), `status` = `new` |

The database never stores the file contents. It stores only the path.

**Run summary** printed (and returned by the Lambda) after each collect:
`found`, `skipped`, `finder_errors`, `new`, `changed`, `unchanged`,
`incomplete`, `errors`.

---

## 7. What this layer produces

One Markdown file per page version, in `data/source-extracted-files/versions/`
(locally) or under the same key in S3.

### File layout

```yaml
---
source: AIHW
url: https://www.aihw.gov.au/reports/dementia/dementia-in-australia/contents/about
title: Dementia in Australia
extracted_at: 2026-10-05T03:12:44+00:00
content_hash: 8f2cfd2c90f8253e...
last_updated: 2026-09-12
page_count: 3
pages:
  - url: https://www.aihw.gov.au/.../contents/about
    last_updated: 2026-09-12
    content_hash: a1b2c3d4...
data_link_count: 2
data_links:
  - https://www.aihw.gov.au/getmedia/.../data-tables.xlsx
---

(report content as Markdown starts here)
```

| Header field | Meaning |
|---|---|
| `source`, `url`, `title` | Which agency and page the text came from. Used to cite findings. |
| `extracted_at` | When the pipeline ran, not a fact about the report. |
| `content_hash` | The hash used for change detection. |
| `last_updated` | The agency's own date for the page. |
| `page_count`, `pages` | The pages combined into this document, each with its own date and hash. |
| `data_link_count`, `data_links` | Downloadable data tables found. Recorded for future use, not downloaded. |

### What Layer 2 does with it

Layer 2 reads the file at `markdown_path` and sends its text to the
extraction model. It quotes passages from it, and each quote is checked
against the same text afterwards. The whole file is read, header included.

---

## 8. Running it

### Setup (once, from the repository root)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Collect needs no API keys and no model. It only reads public web pages.

### Run only this layer through the pipeline

```bash
python pipeline/run.py collect
```

It prints the look-back date, then one line per page:

```
  looking back to 2026-10-13 (14 days)
  AIHW (discovered)  https://www.aihw.gov.au/reports/...
    NEW -> document #7: Dementia in Australia
  ABS (manual)  https://www.abs.gov.au/statistics/health/...
    unchanged
```

See what is stored:

```bash
python pipeline/db.py
```

To change what is tracked, edit `pipeline/collect_settings.json` or
`pipeline/sources.json`.

### Run on AWS

The deployed function `health-insight-pipeline` (handler
`pipeline.lambda_handler.handler`) runs this layer with:

```json
{"stage": "collect"}
```

- `stepfunctions/weekly.asl.json` runs it first each week, then moves on to
  extract and assess.
- On Lambda the data folder is `/tmp/data`, synced with the S3 bucket in
  `PIPELINE_S3_BUCKET`. The database is downloaded at the start of the call
  and uploaded after each page. Each new version file is uploaded **before**
  its database row is written, so the database never points at a file that is
  not in S3.
- To change `sources.json` or `collect_settings.json` on AWS without
  redeploying, upload the edited file to `config/<name>` in the bucket. It
  takes priority over the copy in the code.
- Only one call should run at a time, because two would overwrite each
  other's database.

---

## 9. Problems we solved and why the code looks the way it does

Each entry: **what happened → why it mattered → what we did.**

**1. AIHW hides section titles inside buttons.**
Topic labels in collapsible sections are `<button>` elements, not headings, so
unrelated topics merged into one block (a "Childhood dementia" section ran
straight into an unrelated "data gaps" topic). *Fix:* turn each button's
label into a real heading before extraction.

**2. ABS nests content many layers deep and extraction silently dropped half
of it.**
One section had 32 nested wrappers. A "Crisis support services" section with
two sub-topics kept only the first, duplicated, and lost the second with no
sign of it. *Fix:* expand every wrapper down to its lowest-level pieces and
extract each piece directly, re-attaching each piece's heading. For ABS pages
the document-order walker avoids the problem altogether.

**3. An auto-generated citation line made 37 of 63 reports look changed.**
Each AIHW page got a citation line ending "accessed <today's date>". That
line changes daily, so every re-run changed the page's hash. *Fix:* remove
that line (and `Citation` sections) before hashing, checked against every
saved file.

**4. Silent edits by the agency.**
Finding new pages relies on the agency's own date. If a page's content is
edited without its date changing, a date-based check never looks again. The
standalone runner (section 10) closes this with a rolling re-check. The
deployed pipeline does not, see section 11.

**5. An interrupted run left the state out of step with the saved file.**
A file had been saved but its record was not. Trusting the record would have
created a duplicate version. *Fix (standalone runner):* re-read and re-hash
the saved file instead of trusting the stored hash. In the deployed pipeline
the database is written after the file, with a checkpoint after every page.

**6. Saving a file on Windows corrupted its own hash.**
Python's default text mode turns `\n` into `\r\n`, but some AIHW labels
contain a literal `\r`. Reading the file back gave a different hash from the
text before saving. *Fix:* write and read with newline translation turned
off, so text round-trips exactly.

**7. New page types broke extraction in different ways.**
Turning on automated discovery surfaced AIHW templates never tested by hand:
hub pages, short web articles, microsites. On a short article, 2 of 5 similar
pages lost almost all content while the other 3 were fine, with nothing in
the output to show which. *Fix:* a dedicated, verified extraction path for each
template (section 5.2).

**8. AIHW data-file links were invisible.**
The Data tab is filled in by JavaScript, so the raw HTML contained no
`.xlsx` or `.csv` links at all. *Fix:* send the same request the tab's
JavaScript sends and read the answer.

**9. Chart data looked unrecoverable, but wasn't.**
Some charts embed their numbers as JSON in a script tag. All 36 such widgets
checked also contained a real data table (the chart's accessible
alternative), which normal table extraction already captures. No JSON parser
was needed.

**10. Library tables, lists and captions lost content.**
Cells wrapped in paragraphs shifted columns, a first row vanished, a whole
bullet list was dropped from a block, and chart captions disappeared. *Fix:*
our own table, list and caption handling (section 5.3).

---

## 10. Standalone mode (earlier versions)

Before the database pipeline existed, this folder ran on its own, and that
code is still here. The deployed system does **not** use it, but it is useful
for trying a single URL without setting up the pipeline.

**Interactive prompts** — you type the URLs:

```bash
python collect_and_extract/collect_and_extract.py
```

It asks for at least two AIHW and two ABS URLs (a URL on the wrong domain is
rejected), then asks whether to re-check pages already saved. Files are saved
in `source-extracted-files/AIHW/` and `source-extracted-files/ABS/` **relative
to the folder you run it from**, with a `manifest.json` that stores each URL's
hashes and version history. Pages that are new or changed are also copied to
`source-extracted-files/Current/`.

**Automatic discovery** — the finders pick the URLs:

```bash
python collect_and_extract/discover_and_run.py
python collect_and_extract/discover_and_run.py --lookback-days 30
python collect_and_extract/discover_and_run.py --force-refresh
python collect_and_extract/discover_and_run.py --revalidate-batch-size 50
python collect_and_extract/discover_and_run.py --revalidate-batch-size 0
python collect_and_extract/discover_and_run.py --quiet
```

| Flag | Default | Meaning |
|---|---|---|
| `--lookback-days N` | 90 | Only used the first time a finder has no saved date. |
| `--force-refresh` | off | Re-fetch pages even if saved and unchanged. |
| `--revalidate-batch-size N` | 25 | How many already-saved pages to re-check each run, oldest-checked first, whether or not the agency flagged them. `0` turns it off. |
| `--quiet` | off | Print only new, changed and failed pages, plus the summary. |

This mode keeps one "since" date per finder in `manifest.json`. A finder's
date moves forward only when that finder succeeds, so an outage never skips
what was published meanwhile.

Because this mode writes to its own folder, its files are not picked up by
Layer 2 unless you copy them to `data/source-extracted-files/`.

---

## 11. Known limitations — scope of this release

These describe what this release covers. They are boundaries, not faults.

**Sources and discovery**

- **Two agencies only.** Only `aihw.gov.au` and `abs.gov.au` pages are
  accepted. Other sources named in the later prompts, such as PBS listings or
  the Prescribed List, are not collected here.
- **Three listing sources.** A new report is found only if it appears in
  AIHW's report search, the ABS health articles listing or the ABS release
  calendar. Anything else must be added by hand in `sources.json`.
- **Fixed look-back window.** Each run looks at pages dated in the last 14
  days, plus the pages in `sources.json`. A page found earlier is not
  re-checked unless the agency re-dates it. A silent edit to an old page that
  keeps its date is therefore not detected. The re-check batch described in
  section 10 exists only in standalone mode.
- **Skip rules.** The hub-page and topic skips apply to AIHW only (ABS
  finders are already health-only). The topic list is a fixed setting, so a
  new unrelated AIHW topic needs a settings change.
- **Depends on site structure.** Discovery uses an internal AIHW API and the
  layout of ABS listing pages. If either site changes, that finder fails.
  The failure is reported, the other finders still run, and the missed pages
  appear in a later run while still inside the window.

**Content captured**

- **HTML only.** PDFs are not read.
- **Data files are not downloaded.** `.xlsx`, `.csv` and `.zip` links are
  recorded in the file header, not fetched or read.
- **Chart numbers are captured only if the chart has an accompanying table.**
  Charts drawn by live Tableau embeds contribute their title and description
  but not their values. ABS chart JSON is dropped in favour of the table
  that sits next to it.
- **Narrow methodology detection.** Only a link labelled exactly
  "Methodology" that leads to a `/methodologies/` page is followed. "Explanatory
  notes" or "Quality declaration" pages are not.
- **Templates seen so far.** The extraction paths were built and verified
  against the page types encountered. A new template may come out thin
  without any warning in the output, and there is no automated test suite to
  catch it. Each fix was checked by hand against real pages.
- **Reference removal on AIHW** matches a button to its content panel by id.
  If that link is missing on some page, a warning is printed and the
  reference text stays in.

**Change handling**

- **Versions are whole documents.** If one section of a multi-page report
  changes, the whole report is saved as a new version. Per-section hashes are
  written into the file header but not stored in the database.
- **Changes in our own extraction code look like content changes.** A
  version is a new hash of the text, so improving the extractor can produce
  new versions of unchanged pages. Layer 2 removes insights whose evidence
  quote it has already seen for the same page.
- **Partial first captures are saved.** A never-seen page with sub-pages that
  failed is stored as it is. The missing count is printed but not stored.
- **No version limit and no clean-up.** Version files are never deleted.

**Running**

- **One sequential call.** Collect fetches pages one at a time with a short
  pause, and runs as a single Lambda call. A very large batch of new pages
  would take correspondingly long.
- **One run at a time.** Two simultaneous runs would overwrite each other's
  database.
- **Polite, not policy-aware.** Requests are paced at 0.3 seconds apart, but
  `robots.txt` is not consulted.
- **Standalone mode is separate.** Its manifest, `Current/` folder and
  re-check batch do not feed the database pipeline.
