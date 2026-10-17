"""
AWS Lambda entry point. One function runs every stage; the event says which:

    {"stage": "collect"}
    {"stage": "extract", "limit": 3}     limit: at most this many documents this call
    {"stage": "assess",  "limit": 1}
    {"stage": "brief"}
    {"stage": "brief", "preview": true}  make the PDF without marking anything as briefed

Handler setting on the function:  pipeline.lambda_handler.handler

The Step Functions workflow (stepfunctions/weekly.asl.json) calls this once
per stage, and keeps calling extract/assess until nothing is left waiting -
each call returns "still_waiting" for exactly that.

Each call downloads pipeline.db from S3, runs its stage through run.py, and
uploads the database again after every document. Only one call should run at
a time - two at once would overwrite each other's database.

Required environment variables on the function:
    PIPELINE_S3_BUCKET,
    EXTRACT_MODEL,
    PRIORITY_ASSESSMENT_MODEL

LLM_BACKEND defaults to bedrock. In Bedrock mode, configure AWS_REGION and
allow the Lambda execution role to invoke both models; no API URLs or keys are
required. EXTRACT_REASONING and PRIORITY_ASSESSMENT_REASONING are optional and
default to off.

For the explicit api_key alternative, configure EXTRACT_API_URL,
EXTRACT_API_KEY, PRIORITY_ASSESSMENT_API_URL, and
PRIORITY_ASSESSMENT_API_KEY. This changes only the transport; prompts,
schemas, validation, and downstream processing remain the same.
"""

import os
import sys
from pathlib import Path

# Only /tmp is writable on Lambda. Must be set before storage.py is imported.
os.environ.setdefault("PIPELINE_DATA_DIR", "/tmp/data")
sys.path.insert(0, str(Path(__file__).resolve().parent))

if not os.environ.get("PIPELINE_S3_BUCKET"):
    raise RuntimeError("Set PIPELINE_S3_BUCKET on the Lambda function - without it "
                       "nothing would be saved once the function finishes.")

import run  # noqa: E402


def handler(event, context):
    event = event or {}
    stage = event.get("stage")
    if stage not in run.STAGES:
        raise ValueError(f'event needs "stage": one of {", ".join(run.STAGES)} (got {stage!r})')
    return run.run_stage(stage, limit=event.get("limit"), preview=bool(event.get("preview")))
