"""AWS Lambda adapter for one Priority Assessment S3 handoff object."""

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional
from urllib.parse import unquote_plus

try:
    import boto3
except ImportError:
    boto3 = None


SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from run_priority_assessment import (  # noqa: E402
    DEFAULT_PROMPT,
    DEFAULT_SCHEMA,
    process_one,
)


INPUT_PREFIX = "data/insight-generated-files/"
OUTPUT_PREFIX = "data/priority-tagged-insight-files/"
REVIEW_PREFIX = "data/priority-assessment-review/"


def _event_object(event: Mapping[str, Any]) -> tuple[str, str, str]:
    records = event.get("Records") if isinstance(event, Mapping) else None
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError("Expected exactly one S3 ObjectCreated record")

    record = records[0]
    if not isinstance(record, Mapping) or not str(record.get("eventName", "")).startswith(
        "ObjectCreated:"
    ):
        raise ValueError("Expected an S3 ObjectCreated record")

    try:
        bucket = record["s3"]["bucket"]["name"]
        encoded_key = record["s3"]["object"]["key"]
    except (KeyError, TypeError) as exc:
        raise ValueError("S3 record is missing bucket or object key") from exc

    if not isinstance(bucket, str) or not bucket:
        raise ValueError("S3 record bucket must be a non-empty string")
    if not isinstance(encoded_key, str) or not encoded_key:
        raise ValueError("S3 record object key must be a non-empty string")

    key = unquote_plus(encoded_key)
    if not key.startswith(INPUT_PREFIX):
        raise ValueError(f"Input key must be under {INPUT_PREFIX}")

    filename = key[len(INPUT_PREFIX) :]
    if (
        not filename
        or "/" in filename
        or filename in {".", ".."}
        or not filename.endswith(".json")
    ):
        raise ValueError(
            "Input key must be a flat .json object directly under "
            f"{INPUT_PREFIX}"
        )

    return bucket, key, filename


def _pipeline_args() -> SimpleNamespace:
    return SimpleNamespace(
        prompt=DEFAULT_PROMPT,
        schema=DEFAULT_SCHEMA,
        api_url=os.getenv("PROMPT2_API_URL"),
        api_key=os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY"),
        model=os.getenv("PROMPT2_MODEL"),
        timeout=180,
        plain_json=False,
        assessment_file=None,
    )


def _upload_review_if_present(
    s3_client, bucket: str, review_path: Path
) -> Optional[str]:
    if not review_path.is_file():
        return None

    with review_path.open(encoding="utf-8") as file:
        review_required = json.load(file)
    if not isinstance(review_required, list) or not review_required:
        return None

    review_key = REVIEW_PREFIX + review_path.name
    s3_client.upload_file(str(review_path), bucket, review_key)
    return review_key


def lambda_handler(event, context, *, s3_client=None):
    """Process one Prompt 1 S3 object and write its Priority Assessment handoffs."""
    del context
    bucket, input_key, filename = _event_object(event)

    if s3_client is None:
        if boto3 is None:
            raise RuntimeError("boto3 is required by the AWS Lambda Python runtime")
        s3_client = boto3.client("s3")

    with tempfile.TemporaryDirectory(prefix="priority-assessment-", dir="/tmp") as temp_dir:
        invocation_dir = Path(temp_dir)
        input_dir = invocation_dir / "input"
        work_dir = invocation_dir / "work"
        output_dir = invocation_dir / "output"
        for directory in (input_dir, work_dir, output_dir):
            directory.mkdir()

        input_path = input_dir / filename
        final_path = output_dir / filename
        review_path = (
            work_dir / "processed" / f"{Path(filename).stem}__assessment_review_required.json"
        )
        s3_client.download_file(bucket, input_key, str(input_path))

        try:
            result = process_one(
                input_path,
                _pipeline_args(),
                output_dir,
                work_dir=work_dir,
            )
        except Exception:
            try:
                _upload_review_if_present(s3_client, bucket, review_path)
            except Exception as review_error:
                print(f"Failed to persist review-required output: {review_error}")
            raise

        review_key = _upload_review_if_present(s3_client, bucket, review_path)
        if not final_path.is_file():
            raise RuntimeError(f"Priority Assessment did not create final output: {final_path}")

        output_key = OUTPUT_PREFIX + filename
        s3_client.upload_file(str(final_path), bucket, output_key)
        return {
            "input_bucket": bucket,
            "input_key": input_key,
            "output_key": output_key,
            "review_key": review_key,
            "result": result,
        }
