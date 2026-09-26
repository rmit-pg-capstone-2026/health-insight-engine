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

## Keys in `.env`

Open `.env` in the repo root and set:

| Key | Used by | What to put |
|---|---|---|
| `OPENROUTER_API_KEY` | Layers 2 and 3 | Your OpenRouter key (`sk-or-v1-...`). **The only value you must change.** |
| `PROMPT2_API_URL` | Layer 3 | Leave as is - OpenRouter's endpoint. |
| `PROMPT2_API_KEY` | Layer 3 | Leave as is - reuses `OPENROUTER_API_KEY`. |
| `PROMPT2_MODEL` | Layer 3 | The ranking model. Defaults to `deepseek/deepseek-v4-flash-0731`. |

`.env` is gitignored. Never commit it.

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

## Useful options

```bash
# Layer 2: run one file instead of the whole folder (output goes to insight-extraction-test/runs/)
python insight-extraction-test/extract.py data/source-extracted-files/<file>.md --models deepseek/deepseek-v4-flash-0731 --provider deepinfra

# Layer 2: check a model supports structured output, and its price, before using it
python insight-extraction-test/extract.py --check-models --models deepseek/deepseek-v4-flash-0731

# Layer 3: run one file instead of the whole folder
python priority_assessment/src/run_priority_assessment.py data/insight-generated-files/<file>.json
```
