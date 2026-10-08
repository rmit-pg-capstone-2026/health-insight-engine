# Priority Assessment Lambda PoC

## Purpose

This is a standalone AWS Lambda proof-of-concept (PoC) and reference implementation. Lambda runs code in AWS without a continuously running server. This PoC proved that the existing Priority Assessment module can run independently in AWS.

It is **not the team's final deployment architecture**. The final pipeline is expected to combine Insight Extraction → Priority Assessment → Briefing inside one package and one Lambda. This branch preserves the proven standalone reference so teammates can reuse its processing code and deployment lessons.

## How It Works

```text
S3 input file
    ↓
Lambda handler
    ↓
Existing Priority Assessment processing
    ↓
Preprocessing and evidence checks
    ↓
LLM priority assessment through Bedrock (skipped for zero insights)
    ↓
Schema validation and controlled retry when required
    ↓
Aggregation and consolidation
    ↓
S3 final output + S3 review output when needed
```

S3 is AWS object storage: a bucket holds files identified by keys. An input-file creation event supplies the bucket and key to the handler. The handler downloads the file into a temporary folder and calls the existing `process_one()` function.

Preprocessing checks the supplied evidence and separates insights requiring review. The large language model (LLM) assesses the remaining insights. Validation checks the response structure and consistency; the existing pipeline permits one validation retry. Aggregation joins assessments to the source insights, and consolidation prepares the final handoff. The handler uploads that handoff and any non-empty review artifact to S3.

## S3 Input and Output

All three locations use the bucket named in the incoming event. A prefix is the folder-like beginning of an S3 key.

| Location | Purpose | Example key |
| --- | --- | --- |
| `data/insight-generated-files/` | Prompt 1 JSON from Insight Extraction | `data/insight-generated-files/article.json` |
| `data/priority-tagged-insight-files/` | Final Priority Assessment handoff for Briefing | `data/priority-tagged-insight-files/article.json` |
| `data/priority-assessment-review/` | Insights requiring review | `data/priority-assessment-review/article__assessment_review_required.json` |

The final output preserves the original input filename so the next module can identify the article. Review files are separate from the final handoff. The PoC accepts a flat filename ending in `.json`; nested input keys are rejected.

## Key Design Decisions

- The handler is thin: it handles the event, temporary files, and S3 transfers, then calls existing processing code. It does not duplicate prioritisation rules.
- Each invocation gets a unique folder under `/tmp`, with separate input, working, and final-output folders. These files are temporary; persistent results are in S3.
- Exactly one S3 record is required per invocation. The event and input key are validated explicitly.
- Non-empty review output is uploaded on success and is also attempted if processing later fails. If that upload itself fails, the failure is logged and the original processing exception is preserved.
- The response contains only JSON-safe S3 metadata: `input_bucket`, `input_key`, `output_key`, and `review_key`. Internal temporary paths are not returned.
- Without an API key, Bedrock requests use AWS SigV4 signing, which authenticates requests using AWS credentials. Lambda obtains credentials from its execution role through the normal credential chain; `AWS_PROFILE` is not required.
- Local API-key or AWS-credential authentication and the local command-line entry point remain available.
- Existing prompts, schemas, Priority Assessment v0.3 rules, validation, and retry behaviour remain authoritative.

## Reusable Core Change

[`run_priority_assessment.py`](../src/run_priority_assessment.py) supports an optional working folder, `work_dir`, on `process_one()`.

Normal local execution still uses the module's usual data folder. A Lambda caller or future combined pipeline can provide a separate temporary working folder to keep runs isolated. This is a reusable capability of Priority Assessment itself and is useful for the team's combined Lambda; it is not a final architecture decision.

By contrast, `lambda_handler.py` mainly provides reference integration for this standalone S3-triggered PoC.

| Reusable Priority Assessment functionality | Standalone PoC integration |
| --- | --- |
| `process_one()` and optional working folder | S3 event parsing and S3 transfers |
| Preprocessing, model invocation, validation, aggregation, consolidation | `lambda_handler.py` |
| Existing authentication, prompts, schemas, local CLI | Standalone ZIP build, deployment templates, trigger setup |

## Important Files

| File | Purpose |
| --- | --- |
| [`src/lambda_handler.py`](../src/lambda_handler.py) | Adapts one S3 creation event to existing processing and uploads results. |
| [`src/run_priority_assessment.py`](../src/run_priority_assessment.py) | Reusable processing pipeline and local command-line entry point. |
| [`tests/test_lambda_handler.py`](../tests/test_lambda_handler.py) | Fake-S3 tests, failure/review persistence, and real zero-insight processing without a model call. |
| [`requirements-lambda.txt`](../requirements-lambda.txt) | Dependencies to package for Lambda. |
| [`build_lambda.ps1`](build_lambda.ps1) | Builds and checks the Python 3.12 Linux x86_64 deployment ZIP. |
| [`lambda-config.template.json`](lambda-config.template.json) | Reference runtime, handler, timeout, and environment configuration. |
| [`lambda-trust-policy.json`](lambda-trust-policy.json) | Allows Lambda to assume the execution role. |
| [`lambda-inline-policy.template.json`](lambda-inline-policy.template.json) | Template for input reads, output writes, and model invocation permissions. |
| [`s3-test-event.template.json`](s3-test-event.template.json) | Example one-object event for a controlled test. |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Preparation and controlled deployment instructions. |
| [`deployment-manifest.md`](deployment-manifest.md) | Package contents and runtime assumptions. |
| [`s3-trigger.md`](s3-trigger.md) | Input-prefix trigger setup and notification precautions. |

## AWS Runtime Used by the PoC

The reference deployment uses Python 3.12, x86_64, and handler `src.lambda_handler.lambda_handler`. The ZIP places `src/`, `prompts/`, `schemas/`, and packaged dependencies at its root.

The trigger is an S3 `ObjectCreated` event for the input prefix and `.json` suffix. A directly triggering S3 bucket and Lambda function must be in the same AWS Region. `<AWS_REGION>` in templates must be the actual deployment region, and `moonshotai.kimi-k2.5` must be available there.

Required application environment-variable names are `PROMPT2_API_URL` and `PROMPT2_MODEL` for the Lambda IAM authentication path. The managed runtime supplies AWS region and execution-role credentials. No API key or long-lived credentials are required.

This PoC intentionally relies on the managed Python runtime's `boto3` and `botocore`. They are not bundled. Packaging and pinning them can be considered later for production dependency reproducibility.

The configuration template allows 480 seconds, providing headroom for the existing 180-second model timeout and one retry. The PoC does not change that model behaviour.

## Verification Already Performed

Historical PoC work verified local Lambda tests, package imports, the deployment ZIP build, a manual Lambda invocation, and an automatic S3 → Lambda → S3 invocation using real Bedrock Priority Assessment. Final and review outputs were uploaded successfully.

The first controlled run exposed a response-serialization error after successful uploads: internal `Path` objects could not be returned by Lambda. The handler now returns only S3 metadata, and the corrected response was verified during subsequent PoC testing.

These are historical verified results. This preservation task performs only local checks and Git operations; it does not freshly verify AWS state or rerun paid model tests.

## Known Limitations

- This is a standalone PoC reference only.
- Duplicate S3 event handling and deduplication are not implemented; repeated events may repeat processing.
- Exactly one S3 record and a flat input JSON key are expected per invocation.
- Downstream Briefing execution in AWS was not verified.
- The exact least-privilege scope of the deployed execution-role policies was not audited.
- Dependency rebuilds can resolve different package versions and produce a different ZIP hash. The managed runtime's SDK versions can also change.
- Current AWS state may have changed since successful historical testing.
- The existing local `smoke_test.py` has a known missing fixture at `priority_assessment/data/raw/deepseek_prompt1_output.json`; that issue is separate from the Lambda tests.

## Relationship to the Final Team Architecture

The expected team pipeline is:

```text
One package / one Lambda
    Top-level orchestrator
        ↓
    Insight Extraction
        ↓
    Priority Assessment
        ↓
    Briefing
```

The orchestrator is the entry point that calls each module in order. It should call reusable Priority Assessment processing functions directly, with a suitable working folder. It should not need to invoke this standalone Lambda handler.

The processing code and optional working-folder support are the reusable parts most relevant to that combined pipeline. The standalone handler, packaging, and deployment documentation preserve tested reference code and lessons without requiring the team to retain a separate Priority Assessment Lambda.
