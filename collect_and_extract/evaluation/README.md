# Layer 1 evaluation: scripts and results

The scripts and outputs behind the "Data Collection and Extraction Evaluation" section of the final report. They measure how well Layer 1 (`collect_and_extract/`) finds publications and turns them into Markdown. Nothing here is part of the pipeline, and nothing in the pipeline imports it.

The checks were run on **27 October 2026**, over the pipeline's 14-day window (13 to 27 October), using the repo's own code unchanged. The live pages change over time, so a later run covers a different window and will not reproduce these figures exactly. The saved `results/` files are the record of what was measured.

## What was measured

| Measure | How | Script |
|---|---|---|
| What the finders return | Calls `pipeline/discover.py` with `collect_settings.json` | `scripts/discover_run.py` |
| Discovery recall and precision | Compared with the agencies' public listing pages, read by hand (see `ground_truth.md`) | none (manual) |
| Collection and change detection | Ran `pipeline/run.py collect` twice into an empty data folder: first run creates documents, second run should create none | `scripts/run_collect.sh`, `scripts/dbstats.py` |
| Statistic recall, headings, tables, navigation noise, baselines | Fetches each page, builds a reference from its visible text (minus navigation, footer, scripts), and compares our Markdown, Trafilatura and plain text against it | `scripts/metrics.py`, `scripts/pool.py`, `scripts/summ.py` |
| Why numbers and headings were missed | Re-fetches the pages and classifies each miss (chart description text, reference material, other) | `scripts/gaps.py`, `scripts/g2.py`, `scripts/diag.py`, `scripts/diag2.py` |
| Table cell accuracy | Draws 10 tables at random (5 AIHW, 5 ABS, fixed seed) and compares every cell with the Markdown table; also traces the unexplained numbers | `scripts/tables_check.py` |
| Key-findings cards on AIHW pages | Checks whether each card's text appears in the Markdown | `scripts/overview.py` |

Statistic recall counts decimals, comma-grouped numbers and percentages. The reference is built without using the extractor's own logic, so it is independent of what is being tested.

## Results (`results/`)

| File | Contents |
|---|---|
| `discovery.json` | What the finders returned for the window (found and skipped pages) |
| `collect_log.txt` | Console output of the two `collect` runs |
| `metrics.json` | Per-document metrics for our extractor and both baselines, plus the repeat-extraction check |
| `gaps.json` | Per-document breakdown of missed numbers and headings |
| `tables_log.txt` | The 10 sampled tables, with the unexplained-number contexts at the end |
| `overview_log.txt` | Key-findings cards present and missing, per AIHW document |

Headline figures: 13 of 15 listed health publications returned; 98 of 98 pages retrieved; statistic recall 97.4% of 3,949 figures; 572 of 597 sampled table cells correct (95.8%); an unchanged re-run created 0 new documents.

## Running the scripts

Run them with the project's virtual environment. The scripts were written for a single Windows machine and contain hard-coded paths, so edit these first:

- The repo path, `C:\Users\saive\Documents\health-insight-engine`, in each script.
- The working folder, `C:\Users\saive\AppData\Local\Temp\hie_eval`, where the scripts read and write their JSON files. Create a folder and point them at it.

Suggested order:

1. `discover_run.py <out.json>`, saved as `discovery.json` in the working folder (the other scripts read it).
2. `run_collect.sh` (sets `PIPELINE_DATA_DIR` to an empty folder, so nothing in the real `data/` folder or S3 is touched).
3. `metrics.py <out.json>`, then `pool.py` and `summ.py`.
4. `gaps.py`, then `g2.py`.
5. `tables_check.py` and `overview.py`.

The scripts fetch public AIHW and ABS pages with the same polite delay as the collector. They write nothing into the repo or the pipeline database.

## Known limits of this evaluation

- One 14-day window and 11 publications.
- The sample comes from the same sources the extractor was developed on, so it is not a test on unseen sources.
- The updated-page and incomplete-capture cases of change detection were not exercised.
- The two AIHW releases not returned by the finders (see `ground_truth.md`) were not investigated further.
