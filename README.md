# health-insight-engine

A pipeline that turns public ABS and AIHW health publications into a prioritised healthcare intelligence briefing (PDF) for a private health insurer.

## The four layers

Each layer reads from the previous layer's folder under `data/` and writes to its own.

| # | Layer | What it does | Reads | Writes |
|---|---|---|---|---|
| 1 | `collect_and_extract/` | Fetches AIHW and ABS pages from URLs you enter and converts them to clean markdown. | URLs (typed in) | `data/source-extracted-files/` |
| 2 | `insight-extraction-test/` | Uses an LLM to pull up to 10 source-grounded insights from each document, then checks the quotes and reasoning. | `data/source-extracted-files/` | `data/insight-generated-files/` |
| 3 | `priority_assessment/` | Uses an LLM to rate each insight's relevance and priority, and holds back any whose evidence could not be verified. | `data/insight-generated-files/` | `data/priority-tagged-insight-files/` |
| 4 | `briefing/` | Renders every prioritised insight into a single PDF briefing. | `data/priority-tagged-insight-files/` | `data/briefing-paper/briefing_report.pdf` |

## Setup (once)

From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env    # -n: never overwrites an existing .env
```

If your prompt shows `(base)`, run `conda deactivate` before creating the venv.

In every new terminal after that, you only need:

```bash
source .venv/bin/activate
```

## LLM configuration

For the automated `pipeline/` Extract and Priority Assessment stages, explicitly set either:

```text
LLM_BACKEND=bedrock
```

or:

```text
LLM_BACKEND=api_key
```

Both modes use the same pipeline code and OpenAI-compatible Chat Completions transport.

| Setting | Purpose |
|---|---|
| `LLM_BACKEND=bedrock` | Uses the AWS credential chain and SigV4 authentication. On Lambda, credentials come from the execution role. |
| `LLM_BACKEND=api_key` | Uses generic Bearer-token authentication for an OpenAI-compatible endpoint. |
| `EXTRACT_API_URL`, `EXTRACT_MODEL` | Extraction endpoint and model. |
| `PRIORITY_ASSESSMENT_API_URL`, `PRIORITY_ASSESSMENT_MODEL` | Priority Assessment endpoint and model. |
| `EXTRACT_API_KEY` | Extraction key in `api_key` mode. |
| `PRIORITY_ASSESSMENT_API_KEY` | Priority Assessment key in `api_key` mode. |

In `bedrock` mode, configure AWS credentials using the standard AWS credential chain and set the appropriate AWS region. For example, local development may use an AWS profile through `AWS_PROFILE`. On Lambda, the function uses its execution role.

In `api_key` mode, supply the relevant API key through the environment. This mode can be used with compatible providers that accept Bearer-token authentication, including Amazon Bedrock when using a Bedrock API key.

The standalone layer-2 script (insight-extraction-test/extract.py) still calls OpenRouter directly and requires OPENROUTER_API_KEY. The automated pipeline/ Extract stage uses the shared dual-backend transport described above. The standalone Priority Assessment runner also supports the shared dual-backend transport.

`.env` is gitignored. Never commit credentials.

## Running the pipeline

Run from the repo root, in order.

**1. Collect sources** - prompts for at least two AIHW and two ABS URLs.

```bash
python collect_and_extract/collect_and_extract.py
```

**2. Extract insights** - one call per document.

```bash
python insight-extraction-test/extract.py --models deepseek/deepseek-v4-flash-0731 --provider deepinfra
```

Always pass `--models`. Without it, every default model runs, including a more expensive one.

**3. Assess priority**

```bash
python priority_assessment/src/run_priority_assessment.py
```

Insights held back for review are saved per article in `priority_assessment/data/processed/*__assessment_review_required.json`.

**4. Generate the briefing**

```bash
python briefing/generate_briefing.py
```

The PDF is written to `data/briefing-paper/briefing_report.pdf`, replacing the previous one.

The PDF follows the agreed briefing format: **Executive Summary** (one paragraph), **What Changed This Period** (one line per key development, with its priority), the insight cards grouped into **Clinical**, **Pharmaceutical** and **Prosthesis & Medical Technology Insights** (highest priority first, each keeping its priority tag), then the **Emerging Watchlist**.

The summary, What Changed list and Emerging Watchlist come from one LLM call using the same `LLM_BACKEND` and `PRIORITY_ASSESSMENT_*` settings as stage 3 (override with `EXEC_SUMMARY_*` in `.env`). The answer is checked before it is used: every cited insight must exist, every figure must appear in the insight it cites, and every Watchlist-priority insight must be on the watchlist, with one retry if not. If the LLM is unavailable or still fails, a rule-based version is used instead and the PDF says so. Insight cards are numbered, and the summary links to those numbers.

```bash
python briefing/generate_briefing.py --summary rules   # no LLM call
python briefing/generate_briefing.py --summary none    # no executive summary
```

The prompt is `briefing/prompts/executive_summary_v0.2.md`.

## Automated pipeline (database)

`pipeline/` runs the same four layers without prompts. A SQLite database (`data/pipeline.db`, gitignored) sits between the stages: each stage reads its work from it and writes its results back.

| File | What it is |
|---|---|
| `pipeline/collect_settings.json` | How far back the finders look (`discovery_days`), whether to skip AIHW hub pages, and the AIHW topics to skip. |
| `pipeline/sources.json` | Manual list: older or extra pages to track. Checked every run. |
| `pipeline/discover.py` | Runs the three finders in `collect_and_extract/` and applies the settings above. |
| `pipeline/stages.py` | The four stages as plain functions: a dict in, a dict out. No database code. |
| `pipeline/run.py` | Reads each stage's input from the database, calls the stage, saves the output. |
| `pipeline/db.py` | The database tables. Run it to see what is in the database. |

```bash
python pipeline/run.py                    # collect -> extract -> assess
python pipeline/run.py extract            # one stage only (collect | extract | assess | brief)
python pipeline/run.py brief --preview    # make the PDF, mark nothing (safe to repeat)
python pipeline/run.py brief              # make the PDF and mark its insights as briefed
python pipeline/db.py                     # status: documents, insights, briefings, cost
```

How collect finds pages, every run:

- The finders (AIHW reports, ABS health articles, ABS health statistics releases) return everything dated in the last `discovery_days` (default 14 - wider than the weekly gap, so one missed run loses nothing).
- AIHW hub pages (one level deep, e.g. `/mental-health`) and topics in `aihw_skip_topics` are skipped. ABS finders are already health-only.
- Each found page, plus every page in `sources.json`, is fetched. A page never seen before becomes a new document; a known page becomes a new document only if its content changed. Older discovered pages are not re-checked unless the agency dates them again.
- If a finder fails, the others still run and the summary says so. If some sub-pages of a known report fail to load, the existing version is kept and the page is retried next run.

How it behaves after that:

- Only a page whose content changed becomes a new document. Each version is saved as its own file in `data/source-extracted-files/versions/` (never overwritten); the database stores just its path.
- New insights are compared with those already stored for earlier versions of the same page. Any whose evidence quote matches is dropped, so only new insights are assessed and briefed.
- Insights whose evidence quote is not in the document are held back, same as layer 3.
- A document that fails is retried on the next run, and marked `failed` after 3 tries.
- PDFs go to `data/briefing-paper/briefing_<date>.pdf` and are never overwritten.

### Running it on AWS (Lambda + Step Functions)

One Lambda function, `health-insight-pipeline` (handler `pipeline.lambda_handler.handler`), runs every stage; the event says which:

```json
{"stage": "collect"}
{"stage": "extract", "limit": 3}
{"stage": "assess", "limit": 1}
{"stage": "brief", "preview": true}
```

The Step Functions workflow in `stepfunctions/weekly.asl.json` calls it in order: collect once, then extract and assess in small batches, calling again while the result's `still_waiting` is above 0. So no single call comes near Lambda's 15-minute limit. Brief runs separately.

Build the zip once and upload it to the one function:

```bash
bash build_lambda.sh        # -> dist/lambda.zip (Linux packages for Python 3.12, x86_64)
```

To change `sources.json` or `collect_settings.json` on AWS without redeploying, upload the edited file to `config/<name>` in the bucket - it takes priority over the copy in the code.

On Lambda, files live in `/tmp/data` and are synced with the S3 bucket in `PIPELINE_S3_BUCKET`: each call downloads `pipeline.db`, and uploads it again after every document. Only one call should run at a time.

To start from scratch, delete `data/pipeline.db`. To retry a failed document: `sqlite3 data/pipeline.db "UPDATE documents SET status='new', attempts=0 WHERE id=<id>"` (use `status='extracted'` if it failed at the assess stage).

## Useful options

```bash
# Layer 2: run one file instead of the whole folder (output goes to insight-extraction-test/runs/)
python insight-extraction-test/extract.py data/source-extracted-files/<file>.md --models deepseek/deepseek-v4-flash-0731 --provider deepinfra

# Layer 2: check a model supports structured output, and its price, before using it
python insight-extraction-test/extract.py --check-models --models deepseek/deepseek-v4-flash-0731

# Layer 3: run one file instead of the whole folder
python priority_assessment/src/run_priority_assessment.py data/insight-generated-files/<file>.json
```
