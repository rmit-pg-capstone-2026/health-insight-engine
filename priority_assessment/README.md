# Priority Assessment Pipeline

This folder implements the Priority Assessment module within the health insight pipeline:

`Insight Extraction output -> preprocessing/QA -> Priority Assessment article mode -> validation -> aggregation -> simple consolidation -> briefing_input.json`

## Pipeline responsibilities

The module preserves the agreed handoff between source-grounded insight extraction and priority assessment:

- The Insight Extraction stage remains responsible for atomic, source-grounded insight extraction.
- Priority Assessment performs relevance assessment, the agreed priority criteria, priority classification, and priority rationale.
- Extraction-stage `reasoning` and debug metadata are not passed into Priority Assessment validation.
- Explicit upstream grounding failures (`found_in_source: false`) are quarantined from assessment.
- Priority Assessment article mode assesses every eligible insight independently and returns one assessment per input insight.
- Validation checks schema conformance, insight IDs, order, uniqueness, and relevance/priority cross-field rules.
- Aggregation rejoins Priority Assessment output with the original source-grounded evidence fields.
- Consolidation is deterministic: filter, priority-sort, and section indexing. It does not perform semantic merging.

## Example input and smoke-test fixture

`data/raw/deepseek_prompt1_output.json` is a historical fixture filename containing a sample Insight Extraction output used during integration testing.

Running preprocessing on this fixture produces:

- 9 clean insights ready for Priority Assessment.
- 1 review item (`INSIGHT_008`) because upstream `found_in_source = false`.

The fixture is retained as a reproducible example of the expected handoff from extraction into Priority Assessment.

## Install

```bash
python -m pip install -r requirements.txt
```

## LLM configuration

The runner uses a configurable OpenAI-compatible `/chat/completions` interface so the pipeline is not tied to a single authentication method or provider.

Two backend modes are supported:

### `LLM_BACKEND=bedrock`

Uses the AWS credential chain and SigV4 authentication.

No LLM API key is required.

When running locally, configure AWS credentials using the standard AWS credential chain and set the appropriate AWS region. For example, an AWS profile may be selected through `AWS_PROFILE`.

When running on AWS Lambda, credentials are obtained from the Lambda execution role.

### `LLM_BACKEND=api_key`

Uses Bearer-token authentication against an OpenAI-compatible endpoint.

Configure:

```text
PRIORITY_ASSESSMENT_API_URL=<full chat completions endpoint>
PRIORITY_ASSESSMENT_MODEL=<model name used by that endpoint>
PRIORITY_ASSESSMENT_API_KEY=<API key>
```

API-key mode is provider-neutral. It can be used with compatible third-party providers or with Amazon Bedrock when using a Bedrock API key.

For either backend, configure:

```text
LLM_BACKEND=bedrock
```

or:

```text
LLM_BACKEND=api_key
```

together with:

```text
PRIORITY_ASSESSMENT_API_URL=<full chat completions endpoint>
PRIORITY_ASSESSMENT_MODEL=<model name used by that endpoint>
```

## One-command pipeline run

From this folder:

```bash
python src/run_priority_assessment.py data/raw/deepseek_prompt1_output.json
```

The pipeline performs:

```text
Insight Extraction output
    ->
preprocessing and QA
    ->
Priority Assessment article mode
    ->
validation
    ->
aggregation
    ->
deterministic consolidation
    ->
briefing_input.json
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

If a Priority Assessment article-mode response has already been produced, validation and downstream deterministic processing can be run without making another LLM request:

```bash
python src/run_priority_assessment.py data/raw/deepseek_prompt1_output.json \
  --assessment-file path/to/assessment_results.json
```

This is useful for debugging preprocessing, validation, aggregation, and consolidation separately from model-provider or authentication issues.

## Provider compatibility

If an OpenAI-compatible provider does not support:

```json
{"response_format": {"type": "json_object"}}
```

use:

```text
--plain-json
```

when supported by the runner.

The assessment prompt, schema, validation rules, and downstream processing are independent of the authentication mode.

## Integration behaviour

Only insights that pass the upstream grounding gate are included in the Priority Assessment handoff.

Priority Assessment expects the required handoff fields to be populated for every eligible insight. In particular, an insight intended for assessment must contain the required source-grounded evidence fields, including `evidence_location`.

Insights held back by upstream grounding checks remain available for traceability but are not submitted for Priority Assessment.

## Prompt versions

`priority_assessment_v0.3.md` is retained as the evaluated one-insight development prompt.

`priority_assessment_v0.3_article.md` is the article-level wrapper used by the integrated pipeline to assess multiple insights in one model call.

The article-mode wrapper does not by itself declare the underlying priority methodology to be a final `v1.0`. Assessment prompt version promotion should follow the project's evaluation process.
