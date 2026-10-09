"""
AWS Lambda entry points - one per stage, all in the same zip.

Set each function's handler to one of:
    pipeline.lambda_handler.collect
    pipeline.lambda_handler.extract
    pipeline.lambda_handler.assess
    pipeline.lambda_handler.brief

Each call downloads pipeline.db from S3, runs its stage through run.py, and
uploads the database again after every document. Run the stages one at a
time - two running at once would overwrite each other's database.

Test event (all keys optional):
    {"limit": 1}        extract / assess: at most this many documents this call
    {"preview": true}   brief: make the PDF without marking anything as briefed

Required environment variables on the function:
    PIPELINE_S3_BUCKET, OPENROUTER_API_KEY,
    PROMPT2_API_URL, PROMPT2_API_KEY, PROMPT2_MODEL
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


def _run(stage, event):
    event = event or {}
    return run.run_stage(stage, limit=event.get("limit"), preview=bool(event.get("preview")))


def collect(event, context):
    return _run("collect", event)


def extract(event, context):
    return _run("extract", event)


def assess(event, context):
    return _run("assess", event)


def brief(event, context):
    return _run("brief", event)
