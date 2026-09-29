# RMIT–Medibank Week 9 Priority Assessment Integration Demo

This folder implements the agreed Week 9 module without changing the project architecture:

`Prompt 1 JSON -> preprocessing/QA -> Priority Assessment v0.3 article mode -> validation -> aggregation -> simple consolidation -> briefing_input.json`

## What is preserved from the handoff design

- Prompt 1 remains the owner of atomic/source-grounded extraction.
- Priority Assessment does relevance + Amy's priority criteria + priority + rationale only.
- Prompt 1 `reasoning` and debug metadata are not passed into validate_priority_assessment .
- Explicit upstream grounding failures (`found_in_source: false`) are quarantined.
- Priority Assessment article mode assesses every insight independently and returns one assessment per input insight.
- Validation checks schema, IDs, order, uniqueness, and relevance/priority cross-field rules.
- Aggregation rejoins Priority Assessment output to the source-grounded evidence fields.
- Week 9 consolidation is deterministic only: filter, priority-sort, section indexing. No semantic merging.

## Real DeepSeek smoke test already included

`data/raw/deepseek_prompt1_output.json` is the supplied teammate output.

Running preprocessing on it produces:

- 9 clean insights ready for validate_priority_assessment 
- 1 review item (`INSIGHT_008`) because upstream `found_in_source = false`

## Install

```bash
python -m pip install -r requirements.txt
```

## API configuration

The runner uses a configurable OpenAI-compatible `/chat/completions` endpoint so the Week 9 pipeline is not tied to a provider.

Set:

```text
PROMPT2_API_URL=<full chat completions endpoint>
PROMPT2_API_KEY=<key>
PROMPT2_MODEL=<model name used by that endpoint>
```

If the provider does not support `response_format={"type":"json_object"}`, add `--plain-json`.

## One-command demo

From this folder:

```bash
python src/run_priority_assessment.py data/raw/deepseek_prompt1_output.json
```

Outputs:

```text
data/processed/assessment_input.json
data/processed/assessment_review_required.json
data/assessments/assessment_results.json
data/processed/assessed_insights.json
data/handoff/briefing_input.json
```

## Run without an API call

If a Priority Assessment article-mode response has already been produced, validate and continue the pipeline with:

```bash
python src/run_priority_assessment.py data/raw/deepseek_prompt1_output.json \
  --assessment-file path/to/assessment_results.json
```

This is useful for debugging the deterministic integration stages separately from API/provider issues.

## Important version note

`priority_assessment_v0.3.md` is preserved as the evaluated one-insight development prompt. `priority_assessment_v0.3_article.md` is a separate Week 9 wrapper. This does **not** declare v0.3 to be final v1.0; article mode should later be evaluated against the existing per-insight mode.
