# Health insight engine

This README is written so that someone with **zero prior context** on this
project can read it top to bottom and understand what it does, why it's
built the way it is, and how to run it. If you're new here, start at
section 1 and read in order — later sections assume you know the terms
introduced earlier.

---

## 1. What this project is

**In one sentence:** this project automatically finds Australian health
reports published by two government agencies, downloads them, converts
them into clean text files, and keeps track of every change to every
report over time — so an LLM team can read those text files and pull out
insights, without worrying about web scraping, duplicate reports, or
whether a report they already read has since been quietly updated.

**The two agencies this pulls from:**
- **AIHW** — Australian Institute of Health and Welfare (`aihw.gov.au`).
  Publishes long-form reports (e.g. "Dementia in Australia").
- **ABS** — Australian Bureau of Statistics (`abs.gov.au`). Publishes
  shorter statistical articles and releases (e.g. "Deaths due to acute
  respiratory infections").

**What "clean text" means here:** a real webpage is full of things that
aren't the actual content — navigation menus, "Download as PDF" buttons,
cookie banners, related-article widgets, chart UI controls. This project's
job is to strip all of that away and keep only the real report content, as
Markdown, because Markdown is what gets fed into an LLM later. Getting this
right is most of what this codebase actually does — see section 9 for the
specific problems that came up and how each one was solved.

**What this project explicitly does NOT do** (see section 8 for the full
list): it doesn't call an LLM itself, doesn't parse PDFs, doesn't download
the actual `.xlsx`/`.csv` data files it finds links to (just records that
they exist), and isn't wired into any production codebase — it's a
standalone sandbox that produces files for someone else's pipeline to pick
up afterward.

---

## 2. Current status — two phases exist, one is current

This project was built in two phases, and **the code for both phases is
still in this folder right now.** Understanding this is the single most
important thing for a new reader, because looking at the code without this
context is confusing — there are two different "front doors" into the same
engine.

### Phase 1 — manual prototype (where this project started)

The very first version of this pipeline worked like this: you run the
script, it asks you to type in two AIHW URLs, then asks "do you have more
URLs?" in a loop until you say no, then does the same thing for ABS, then
asks a yes/no question about whether to re-check everything for updates.
A human has to already know which URLs to paste in.

### Phase 2 — automated discovery (what this project is now)

Phase 2 adds a layer in front of Phase 1 that does the "which URLs" step
automatically. Instead of a human typing in URLs, three small programs ask
each agency's website directly: *"what have you published that's new since
the last time I checked?"* Those URLs are then fed into the **exact same**
fetch/extract/save machinery Phase 1 always had — Phase 2 did not rewrite
that part, it just gave it an automatic source of input instead of a human
typing at a prompt.

### Side-by-side comparison

| | Phase 1 (manual) | Phase 2 (automated) |
|---|---|---|
| **You run** | `python collect_and_extract.py` | `python discover_and_run.py` |
| **How URLs are found** | You type them in, one at a time | Discovered automatically from each agency's own website |
| **Checking for silent updates** | One manual yes/no question, checks *everything* if you say yes | A small automatic batch every run, checks a *few* oldest-checked URLs |
| **Is this the recommended way to run the project today?** | No — kept as a fallback, explained below | **Yes — this is primary** |

### Why Phase 1's code is still here

Phase 1 isn't dead code — it's kept on purpose as a manual escape hatch.
The three automatic "discovery" programs can only find reports that show
up on the specific listing pages they check (see section 8). If a report
ever needs to be added that doesn't show up there for whatever reason,
Phase 1's interactive prompt is still the way to feed that one URL through
the pipeline by hand. The two entry points are completely independent —
running one never calls the other.

---

## 3. Architecture — how the pieces fit together

### The shape of the system

```
                 ┌─────────────────────┐
                 │  discover_aihw.py    │──┐
                 ├─────────────────────┤  │
                 │ discover_abs_        │──┼──> discover_and_run.py
                 │ articles.py          │  │      (the conductor)
                 ├─────────────────────┤  │             │
                 │ discover_abs_        │──┘             │
                 │ statistics.py        │                ▼
                 └─────────────────────┘      process_source()
                                               (lives inside
                                                collect_and_extract.py)
                                                        │
                                                        ▼
                                          fetch → extract → hash → save
                                                        │
                                                        ▼
                                          source-extracted-files/
                                          (the actual output)
```

### A few terms you'll see constantly, explained once

- **Cursor** — a saved timestamp, one per discovery source, recording
  "the last time I checked this source, here's what I'd already seen."
  Each of the three discovery sources keeps its own cursor, stored in
  `manifest.json` under a special `_discovery` key.
- **Manifest** — `source-extracted-files/manifest.json`. A single JSON
  file that remembers everything this pipeline needs to recall between
  runs: which URLs have already been saved, what their content looked
  like last time, when they were last checked, and the three discovery
  cursors. Without it, every run would look like the very first run.
- **Content hash** — a short fingerprint (SHA-256) of a report's extracted
  text. Two runs that produce the exact same hash mean "nothing really
  changed," even if the page's raw HTML looks different (agencies
  reshuffle page layout without changing content fairly often). This is
  how the pipeline tells a *real* content change apart from a cosmetic one.
- **Revalidation** — periodically re-checking a report that's already been
  saved, even though nothing told this pipeline it had changed. Explained
  fully below — it exists to catch changes an agency makes *without*
  updating their own "last updated" date.
- **Versioning** — never deleting or overwriting a saved report. If a
  report's content genuinely changes, the old file is kept and a new file
  is added alongside it.

### Walking through one real run, step by step

Say you run `python discover_and_run.py` today. Here's exactly what
happens, in order:

1. **Load the manifest.** Everything this pipeline remembers from every
   previous run is read from `source-extracted-files/manifest.json`. If
   this file doesn't exist yet (first run ever), it starts from empty.
2. **Ask each of the three discovery sources "what's new?"**
   - `discover_aihw.py` calls AIHW's internal report-search API and asks
     for everything published since its own saved cursor.
   - `discover_abs_articles.py` checks ABS's public "Articles" listing
     page, filtered to the Health topic.
   - `discover_abs_statistics.py` checks ABS's release calendar, also
     filtered to Health.
   - These three run independently. If one of them fails (e.g. the
     website is down, or its HTML changed shape unexpectedly), that one
     source is skipped with a warning — its cursor is **not** moved
     forward, so nothing it might have found gets silently missed later.
     The other two sources are unaffected.
3. **Fetch, extract, and save every newly discovered URL.** Each URL goes
   through `process_source()`: download the page, run it through the
   correct extraction logic for that agency (AIHW and ABS need genuinely
   different approaches — see section 9), compute a content hash, compare
   it against what the manifest remembers, and save a new `.md` file only
   if the content actually changed or it's brand new.
4. **Revalidate a small batch of older, already-saved reports.** Separately
   from step 2/3, the pipeline also picks a handful of reports it hasn't
   personally re-checked in the longest time (regardless of whether the
   agency flagged them as updated) and re-runs them through the exact same
   fetch/extract/save path. This is the safety net described below.
5. **Save the updated manifest.** New discovery cursors, new content
   hashes, new "last checked" timestamps — all written back to
   `manifest.json` so the next run picks up exactly where this one left
   off.

### Why revalidation exists as its own separate step

This is one of the most important design decisions in the whole project,
so it's worth explaining in plain terms here (the full incident that
caused this is in section 10, Scenario 4).

Step 2 above — discovery — only works by trusting each agency's own
"here's what's new" signal (for AIHW and ABS, that's a publish/update
date). But what if an agency quietly edits a report's actual content
*without* updating that date? Discovery would compare the (unchanged) date
against its cursor, conclude "nothing new here," and that report would
never be looked at again — not next week, not next year, not ever, no
matter how many times this pipeline runs.

Revalidation exists purely to close that gap. It doesn't trust the
agency's "updated" signal at all — it just periodically re-fetches reports
that haven't personally been re-checked in a while and compares the
content hash directly. It's slower (a real re-fetch, not just a date
comparison) so it only checks a small batch per run (25 by default)
instead of everything — a full sweep of ~104 tracked reports takes about 5
runs, which is an acceptable tradeoff since these reports have been
observed to change content maybe a couple of times a year, not daily.

---

## 4. Setup

```
pip install -r requirements.txt
```

That installs the four packages this project depends on: `requests` (HTTP
fetching), `trafilatura` (HTML-to-Markdown conversion), `lxml` (HTML
parsing), and `beautifulsoup4` (also HTML parsing, used in a few specific
spots). No API keys, no accounts, no config files needed — everything else
this pipeline needs, it figures out from the public web pages themselves.

---

## 5. Usage

### Automated (current, recommended entry point)

```
python discover_and_run.py
```

Running it with no flags uses sensible defaults for everything. The
available flags, for when you want non-default behavior:

| Flag | Default | What it does | When you'd use it |
|---|---|---|---|
| `--lookback-days N` | `90` | Only matters the *very first time* a discovery source has no saved cursor yet — tells it how far back to look for a starting point. | Bootstrapping a source for the first time, or re-bootstrapping one after wiping the manifest. |
| `--force-refresh` | off | Re-fetches and re-extracts every URL *discovery finds this run*, even ones that already have an unchanged, cached copy. | You suspect something about the extraction logic itself changed and want to re-verify already-saved reports, not just new ones. |
| `--revalidate-batch-size N` | `25` | How many already-saved reports to re-check this run (oldest-checked-first), independent of what discovery found. `0` turns this off entirely for this run. | Turn it up to sweep through the backlog faster; turn it to `0` for a quick discovery-only check. |

Example commands:
```
python discover_and_run.py                             # normal run, all defaults
python discover_and_run.py --lookback-days 30           # bootstrap a source looking back only 30 days
python discover_and_run.py --force-refresh               # force re-check of everything discovery finds
python discover_and_run.py --revalidate-batch-size 50    # sweep through the backlog twice as fast
python discover_and_run.py --revalidate-batch-size 0      # discovery only, skip revalidation this run
```

**What you'll see printed to the screen**, roughly:
```
--- Discovery summary ---
  AIHW: 2 URL(s)
  ABS:  1 URL(s)

Extracting AIHW URLs...
  Saved: source-extracted-files/AIHW/some-report-...md [AIHW, CHANGED, ...]

--- Revalidation: re-checking 25 previously-saved URL(s), oldest-checked-first ---
Extracting AIHW URLs...
  Already have: ...md (last checked 2026-09-01) - skipping re-fetch
  ...

Done.
```
A `Skipped (...)` line means one specific URL failed (bad network request,
unreachable page, etc.) — it does not stop the rest of the batch from
processing.

### Manual (legacy, still available as a fallback)

```
python collect_and_extract.py
```

This is Phase 1's original interactive flow:

1. It asks: `Please enter AIHW-1 URL:` and then `Please enter AIHW-2 URL:`
   — both mandatory. A URL that isn't on `aihw.gov.au` is rejected and
   re-asked.
2. Then it asks `Do you have more URLs? (y/n)` in a loop. Answer `y` to add
   AIHW-3, AIHW-4, and so on; answer `n` to move on.
3. The same two steps (steps 1–2) then repeat for ABS URLs.
4. Once both lists are finalized, it asks once: `Re-check already-extracted
   URLs for content updates? (y/n)`. Answering `n` (or just pressing Enter)
   skips any URL that's already saved and unchanged — fast. Answering `y`
   force-refreshes everything you just typed in.
5. Every URL is then fetched, extracted, and saved exactly the same way
   the automated path does it — same functions, same manifest, same
   versioning rules.

Use this when you have a specific URL in hand that the automated discovery
sources don't surface on their own.

---

## 6. Project structure

```
health-insight-engine/
├── discover_and_run.py            <- PRIMARY entry point (Phase 2)
├── discover_aihw.py                <- discovery source: AIHW's report-search API
├── discover_abs_articles.py        <- discovery source: ABS "Articles" listing
├── discover_abs_statistics.py      <- discovery source: ABS release calendar
├── collect_and_extract.py          <- the shared engine + Phase 1 manual entry point
├── requirements.txt                <- the 4 Python packages this needs
├── README.md                       <- this file
└── source-extracted-files/         <- all output lives here (created automatically)
    ├── manifest.json               <- the pipeline's memory across runs
    ├── AIHW/*.md                   <- every version of every AIHW report, ever
    ├── ABS/*.md                    <- every version of every ABS report, ever
    └── Current/
        ├── AIHW/*.md               <- only AIHW reports new/changed in the most recent run
        └── ABS/*.md                <- only ABS reports new/changed in the most recent run
```

| File | What's actually in it |
|---|---|
| `discover_and_run.py` | The conductor: calls the three discovery modules, hands their output to the shared engine, runs revalidation, saves the manifest. This is what you run day-to-day. |
| `discover_aihw.py` | Talks to AIHW's own internal report-search API directly (not scraping HTML — it calls the same API AIHW's own search box uses). |
| `discover_abs_articles.py` | Scrapes ABS's public "Articles" listing page, Health topic only. |
| `discover_abs_statistics.py` | Scrapes ABS's release calendar, Health topic only. |
| `collect_and_extract.py` | The biggest file by far. Contains: URL fetching, AIHW-specific extraction logic, ABS-specific extraction logic, shared extraction helpers, file saving, change detection, versioning, and — separately — Phase 1's manual interactive `main()` function. |
| `source-extracted-files/manifest.json` | One big JSON object. Every report URL is a key; the value holds its title, every version it's ever had, and timestamps. A special `_discovery` key (not a real report) holds the three discovery cursors. |
| `source-extracted-files/<AIHW\|ABS>/*.md` | The permanent historical archive — every distinct version of every report that's ever been extracted, going back to the first time this pipeline ran. Nothing in here is ever deleted or overwritten. |
| `source-extracted-files/Current/<AIHW\|ABS>/*.md` | A much smaller, "what's worth a second look" folder — only reports that were new or had real content changes in the most recent run. This file gets overwritten each time that specific report changes again. |

---

## 7. Output / data format

### How files are named

Every saved report file looks like this:
```
dementia-in-australia-8f2cfd2c-90f8253e.md
└──────── title ───────┘ └ url hash ┘ └ content hash ┘
```
- The **title** part is the report's title, lowercased and cleaned up to
  be filename-safe.
- The **URL hash** (8 characters) guarantees two different reports that
  happen to share a generic title (e.g. two different reports both titled
  "Summary") never overwrite each other.
- The **content hash** (8 characters) is what makes versioning work: if a
  report's content hasn't changed, re-running the pipeline produces the
  exact same hash, so it reuses the exact same filename — nothing new gets
  written. Only a genuine content change produces a new hash, and
  therefore a new file, alongside the old one (which is never deleted).

### What's inside each file: the frontmatter

Every `.md` file starts with a block of metadata (between two `---` lines)
before the actual report content. This is called **frontmatter**, and it
looks like this (illustrative example):

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

(the actual extracted report content starts here, as Markdown)
```

**If you're on the LLM team reading this**, here's which of those fields
are actually worth sending to a model, and which are purely this
pipeline's own internal bookkeeping:

| Field | What it's really for | Send it to the LLM? |
|---|---|---|
| `source`, `url`, `title` | Knowing which agency and which exact page a piece of content came from | **Yes** — needed so the LLM (or a human) can cite findings back to a real source |
| `last_updated` | How current the underlying statistics actually are | **Yes** — useful context, e.g. "this stat is from a report last updated 2 years ago" |
| `extracted_at` | When *this pipeline* happened to run, not a fact about the report | Only marginally useful |
| `content_hash` | This pipeline's own way of detecting if a report changed since last time | **No** — meaningless to anything outside this repo |
| `page_count`, `pages:` | Lets this pipeline pinpoint which *specific section* of a multi-page report changed, instead of just "something changed" | **No** — pure bookkeeping, and on a large report this can be the single biggest chunk of the whole frontmatter block |
| `data_link_count`, `data_links:` | Links to the underlying `.xlsx`/`.csv`/`.zip` data tables a report references (not downloaded by this pipeline, just recorded) | Not useful for *text* extraction, but **don't throw these away** — a future phase that reads actual numeric tables will need them |

**Why this matters in practice:** the frontmatter adds roughly 1.3%–6.3%
of a file's total size — on a large multi-section report, that can be over
10,000 characters of pure bookkeeping that costs real money/tokens in an
LLM prompt for zero reasoning value. **Recommended handling:** split each
file on the closing `---` line, send only the body below it to the model,
and if you still want provenance in the prompt, re-add just `title` + `url`
+ `last_updated` as plain text instead of the raw YAML block.

One more detail: inside the body itself, each combined section also
carries its own small `Source: <url>` line. This is intentional and
separate from the frontmatter — if your pipeline later splits these
documents into smaller chunks for a retrieval/embedding system, a chunk
pulled out on its own will still carry this line, so it stays traceable
back to its exact source page even without its original frontmatter.

### What's inside `manifest.json`

One JSON object. Every key is a canonical report URL (after redirects are
resolved), except for one special `_discovery` key. Illustrative shape:

```json
{
  "_discovery": {
    "last_run_at": {
      "aihw": "2026-10-05T00:00:00+00:00",
      "abs_articles": "2026-10-05T00:00:00+00:00",
      "abs_statistics": "2026-10-05T00:00:00+00:00"
    }
  },
  "https://www.aihw.gov.au/reports/.../contents/about": {
    "title": "Dementia in Australia",
    "first_seen_at": "2026-08-01T00:00:00+00:00",
    "last_seen_at": "2026-10-05T00:00:00+00:00",
    "last_changed_at": "2026-09-12T00:00:00+00:00",
    "last_revalidated_at": "2026-10-05T00:00:00+00:00",
    "versions": [
      { "content_hash": "aaa111...", "path": "source-extracted-files/AIHW/old-file.md", "created_at": "2026-08-01T00:00:00+00:00", "status": "superseded" },
      { "content_hash": "bbb222...", "path": "source-extracted-files/AIHW/new-file.md", "created_at": "2026-09-12T00:00:00+00:00", "status": "current" }
    ],
    "pages": { "...": "per-section hash/date detail, same idea as the top level" }
  }
}
```

- `versions` is the full history for that URL — every genuinely distinct
  version it's ever had, oldest first, with exactly one marked `"current"`
  at any time and the rest marked `"superseded"`.
- `last_revalidated_at` is what drives revalidation's "oldest-checked-first"
  ordering (section 3) — it gets updated on *every* check of that URL,
  whether or not anything actually changed.

---

## 8. Known limitations — what this deliberately doesn't do

- **Discovery only sees what its three listing pages show it.** AIHW's
  search API, ABS's Articles listing, and ABS's release calendar are the
  *only* places this pipeline looks for new reports automatically. A
  report published somewhere else on either site won't be found — use the
  manual path (section 5) for that one.
- **Methodology-page detection is narrow on purpose.** It only recognizes
  one specific pattern: a link literally labelled "Methodology". Other
  possible companion pages (e.g. "Explanatory notes", "Quality
  declaration") aren't searched for.
- **No PDF support.** If a URL ends in `.pdf`, nothing special happens —
  the underlying extraction library only understands HTML.
- **No limit on how many versions a report can accumulate, and nothing
  ever gets automatically deleted.** This was a deliberate choice, not an
  oversight — these reports have been observed to genuinely change content
  maybe a couple of times a year, so unbounded growth isn't a real problem
  yet. Worth revisiting only if some report turns out to be far more
  volatile than that.
- **Revalidation and manual force-refresh are both tied to *runs*, not to
  a calendar.** There's no scheduler or cron job built in — someone has to
  actually run `discover_and_run.py` for any of this to happen. This is
  intentional for the same "doesn't need to be tight yet" reasoning as the
  point above.
- **No automated test suite.** Every fix described in section 9/10 below
  was verified by hand against real live pages during development — there
  is no committed set of tests that would catch a regression automatically
  if this code changes in the future.
- **Not wired into any production codebase.** This duplicates logic that
  may also exist elsewhere (e.g. a team's own `src/common/fetch.py`) — it
  is a standalone demo, not the production integration.
- **No LLM step at all.** This pipeline's job ends at producing clean
  `.md` files. Reading them and extracting insights is a separate,
  later phase owned by someone else.
- **One defensive gap, flagged but not yet seen in practice:** AIHW's
  References/Bibliography sections are removed by matching a button
  element to its content panel via an `aria-controls`/`id` link in the
  page's HTML. If that link is ever missing or broken on some page this
  pipeline hasn't encountered yet, a warning is printed, but the
  unlabeled content would still end up in the output, because the
  downstream safety net for stripping references works by matching
  *headings*, and this content wouldn't have one.

---

## 9. Design notes — the reasoning behind non-obvious decisions

This section explains *why* things work the way they do, for anyone
making future changes. Section 10 below tells the same underlying stories
but framed as concrete problem → solution scenarios, which may be the
easier starting point for a first read.

**Why AIHW and ABS need completely different extraction code.** A simple
one-pass "convert this whole page to Markdown" approach works fine for
AIHW pages but actively loses content on ABS pages, because of how deeply
ABS nests its real content inside wrapper `<div>` elements — a scoring
algorithm looking at the page as fragments tends to pick one nested piece
and silently discard its siblings. ABS extraction instead walks every
real element on the page in the order it actually appears and converts
each one directly, so there's no scoring step left to lose anything.

**Why References/Bibliography sections and AIHW's citation line are both
removed.** Bibliography lists are low-value for insight extraction, so
that one's simple. The more important case is a single auto-generated
line that includes today's date — because it changes every single day
regardless of whether the report's real content changed, and an early
version of this pipeline's change-detection logic couldn't tell that
apart from a genuine content change, producing a huge batch of false
"this report changed!" flags.

**Why nothing is ever overwritten (versioning).** The purpose of this
whole pipeline is to produce *traceable* evidence for insight reports — if
an agency revises a report after someone has already cited a fact from
it, silently overwriting the old file would destroy the one proof of what
the evidence actually said at the time it was cited.

**Why revalidation exists separately from discovery.** Already explained
in detail in section 3 — the short version is that discovery alone can be
permanently fooled by a source that edits content without updating its own
"last updated" signal.

**A real bug that was found and fixed along the way, worth knowing about
if you ever touch file-saving code on Windows:** saving a file using
Python's normal text-write mode silently translates `\n` into `\r\n` on
Windows. That's invisible almost all the time, but a few AIHW labels carry
a literal `\r` character already baked into their source HTML — and
translating the surrounding characters while leaving that one alone made
re-reading a freshly-saved file produce a *different* hash than hashing
the exact same text before it was ever saved, which looked exactly like a
real content change. Fixed by disabling that automatic translation
entirely wherever this pipeline reads or writes a report file.

---

## 10. Use case scenarios — real situations encountered and how they were solved

This section tells the same engineering history as section 9, but as
concrete "here's what happened" stories. Each one follows the same shape:
**Situation → Why it mattered → How it was solved.**

### Scenario 1: AIHW hides section titles inside collapsible buttons, not real headings

**Situation.** AIHW reports often group content into expandable/collapsible
sections — click a topic name, it expands to show the content underneath.
On a real page, a topic label like "Impact on health, aged care and social
systems" turned out to be a plain `<button>` element in the HTML, not a
heading tag (`<h2>`, `<h3>`, etc.) at all — the extraction library had no
way to know that one topic ended and the next began.

**Why it mattered.** Without a real heading marking the boundary, two
completely unrelated topics were silently merging into one undifferentiated
block of text in the extracted output — confirmed on a real report where a
"Childhood dementia" section flowed directly into an unrelated "data gaps
and limitations" topic with no separation between them at all.

**How it was solved.** Before running the main extraction step, this
pipeline first scans the raw page for these specific button elements and
converts each one's own label text into a real heading tag, so by the time
extraction actually runs, the page looks like it always had proper headings.

### Scenario 2: ABS nests content so deeply that extraction silently drops half of it

**Situation.** An ABS page's real content sat many layers deep inside
repeated wrapper `<div>` elements. A section could contain several
sub-topics (a callout box, a collapsible sub-section, a chart-and-table
pairing, a plain paragraph) nested inside each other — one real section
was found to have 32 such nested layers.

**Why it mattered.** The extraction library's normal approach picks out
what it thinks is "the" main content fragment and ignores the rest.
Confirmed on a real "Crisis support services" section with two sub-topics
side by side ("24 hours, 7 days" and "COVID-19") — only the first one
survived in the output (and was even duplicated); the second vanished
completely, with nothing in the output hinting that anything was missing.

**How it was solved.** Instead of trusting that automatic selection, this
pipeline recursively expands every nested wrapper all the way down to its
real individual pieces, and extracts each piece directly and completely,
re-attaching each piece's own heading along the way so nothing ends up as
floating, unlabeled text.

### Scenario 3: An auto-generated citation line made it look like 37 reports had changed, when none of them had

**Situation.** Every extracted AIHW page automatically got a short
citation line added to it (something like "AIHW (2026) Dementia in
Australia, AIHW, Australian Government, accessed 3 October 2026."). The
"accessed <date>" part in that line is simply *today's date* — the date
this pipeline happened to run — not anything the actual report page says.

**Why it mattered.** Because that one line changes every single day purely
from being re-extracted on a different date, and this pipeline detects
"did this report change?" by comparing a fingerprint of its *entire* text,
that one constantly-changing line made it look like real content had
changed. In one real run, 37 out of 63 reports got flagged as "changed"
this way — none of them had actually changed on the agency's website at
all.

**How it was solved.** This specific auto-generated citation block is now
recognized and removed before the fingerprint is calculated, the same way
real References/Bibliography sections already were. Verified afterward
against every single saved file individually (not just a pattern search)
to confirm the fix actually holds and no real content was accidentally
caught by the same rule.

### Scenario 4: An agency could silently edit a report and this pipeline would never notice, ever

**Situation.** This pipeline's automatic discovery step only knows a report
might have changed by checking the agency's own self-reported "last
updated" date against what it saw last time. That check never looks at the
actual saved content at all — it fully trusts the agency's own date field.

**Why it mattered.** If an agency quietly edits a report's real content —
a correction, a backend data refresh — without ever bumping that visible
date, discovery's comparison stays "nothing new" forever for that one
report. It would never be re-checked again, by anyone, no matter how many
times this pipeline runs in the future. This wasn't a hypothetical: the one
genuine silent content change actually found during development (on the
"chronic conditions dashboard" report) was only caught by a one-off,
expensive, manual re-check of every single tracked report — exactly the
kind of check nobody should have to remember to run by hand.

**How it was solved.** The automated pipeline now runs a small, bounded
"revalidation" sweep every single time it runs — a batch of the reports
it's personally re-checked least recently get re-fetched and re-compared
for real, regardless of what the agency's own date field says. Over
several runs, every tracked report eventually gets this real check, without
anyone having to remember to trigger it. The first full sweep across all
104 tracked reports came back with zero silent changes found — which is
the expected, reassuring result, not a sign the fix was unnecessary; the
value of this fix is in it continuing to confirm that on every future
sweep.

### Scenario 5: A run getting interrupted left the manifest out of sync with the actual saved file

**Situation.** This pipeline saves a report's `.md` file and updates its
record in `manifest.json` as two separate steps. On a real run that got
killed partway through (e.g. the process was stopped), a report's file had
already been correctly saved with its new content — but the manifest's
record of that file's fingerprint never got written before the process
died.

**Why it mattered.** If the pipeline simply trusted the manifest's
(now-stale) fingerprint on the next run, it would wrongly conclude that the
file's actual, already-correct content was "new" all over again, creating
a pointless duplicate version of something that hadn't changed a second
time.

**How it was solved.** Before trusting the manifest's recorded fingerprint
for any comparison, this pipeline now re-reads the actual saved file
straight off disk and re-calculates its real fingerprint on the spot,
rather than relying on what the manifest merely remembers. The manifest is
treated as a cache that can go stale, never as the source of truth.

### Scenario 6: Saving a file on Windows quietly corrupted its own fingerprint

**Situation.** When Python writes a text file using its normal default
settings, it automatically converts every plain `\n` line ending into
`\r\n` on Windows. Normally invisible — but a handful of AIHW labels (e.g.
an "...Updated 23 Sep 2026" button caption) carry a literal `\r` character
that was already present straight from the source HTML, before this
pipeline ever touched it.

**Why it mattered.** Translating all the surrounding `\n` characters while
leaving that one pre-existing `\r` untouched meant that reading a file
right back after writing it produced a *different* fingerprint than
fingerprinting the exact same text just before it was saved — confirmed
directly by writing, then immediately reading back and comparing. That
inconsistency could make an unchanged report look like it had changed,
purely from the act of saving and re-reading it.

**How it was solved.** Both the saving step and the re-checking step now
explicitly disable that automatic newline translation, so a file's content
round-trips byte-for-byte no matter what line-ending characters it
contains.

### Scenario 7: Turning on automated discovery immediately found page types manual testing had never seen

**Situation.** Once the automated discovery pipeline started running for
real, it very quickly surfaced AIHW page types nobody had tested by hand
before — "topic hub" pages (like a general "Hospitals" overview page),
short single-topic "web article" pages, and "microsite" landing pages —
each one built on a different underlying page template than the
long-report pages this pipeline was originally designed around.

**Why it mattered.** Each of those templates broke extraction in its own
way. One real example: on a short "web article" page, 2 of 5 similar
sibling articles in the same report lost almost all of their content (down
to a tiny citation block and a nav list) while the other 3 extracted just
fine — same template, same website, same run, with nothing in the output
flagging which pages were silently broken.

**How it was solved.** Each newly-discovered page template got its own
dedicated extraction fallback, built and verified against the real pages
that exposed the problem (not just the first one found) — including, along
the way, fixing related gaps in how flat runs of headings, plain bullet
lists, and specific chart-widget types were each being handled.

### Scenario 8: AIHW's downloadable data files were completely invisible to this pipeline

**Situation.** AIHW report pages have a "Data" tab listing downloadable
`.xlsx` data tables — but a direct check of a real report's raw HTML
confirmed there were **zero** occurrences of `.xlsx`, `.csv`, or similar
file extensions anywhere in the page source this pipeline actually
receives.

**Why it mattered.** That tab's content is loaded afterward by AIHW's own
JavaScript, which makes a separate request to AIHW's own internal API
after the page loads in a real browser. Since this pipeline only fetches
the initial HTML (it doesn't run a browser or JavaScript), it was recording
zero data-file links for every single AIHW report, even when real data
tables genuinely existed.

**How it was solved.** The exact same API request AIHW's own JavaScript
makes is replayed directly by this pipeline, using the same identifying
information (report ID, etc.) that's already present in the HTML it does
receive — no browser or JavaScript execution needed. Verified on real
reports that this recovered genuine data-table links that had been
completely invisible before.

### Scenario 9: A chart's data looked unrecoverable, until it turned out it already wasn't

**Situation.** Some AIHW charts embed their underlying numeric data as raw
JSON inside a `<script>` tag — initially flagged as a real gap that would
need a dedicated JSON parser built specifically for it, since the pipeline
had no way to read numbers out of embedded JSON at the time.

**Why it mattered.** Before spending the effort building that parser, every
single one of these chart widgets (36 of them, found via a full check of
every page that had this pattern — not just the one originally spotted)
was checked directly against the real page.

**How it was solved.** It turned out every single one of those 36 widgets
*also* includes a real, already-populated `<table>` right alongside the
JSON — the chart's own built-in accessible alternative, intended for screen
readers. This pipeline's existing table-extraction logic already picks
that up automatically as part of normal extraction. No JSON parser was
needed at all — the data had already been fully captured the whole time,
just not yet confirmed.
