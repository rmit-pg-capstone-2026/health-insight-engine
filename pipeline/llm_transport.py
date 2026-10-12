"""Small shared transport for OpenAI-compatible chat completions.

The pipeline can run all LLM stages through either:
- Amazon Bedrock Runtime using the Lambda/SDK AWS credential chain + SigV4, or
- an OpenAI-compatible bearer-key endpoint (for example OpenRouter).

Stage-specific prompts, schemas and validation stay in stages.py. This module
only owns authentication, HTTP transport and bounded retries for transient
failures.
"""

import json
import os
import random
import time
from typing import Any, Dict, Optional, Tuple

import requests

try:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
except ImportError:  # clearer error if someone installs only partial deps
    boto3 = None
    SigV4Auth = None
    AWSRequest = None


VALID_BACKENDS = {"bedrock", "api_key"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


def backend_from_env() -> str:
    raw = os.environ.get("LLM_BACKEND")
    if not raw:
        raise RuntimeError("Set LLM_BACKEND to 'bedrock' or 'api_key'")
    backend = raw.strip().lower()
    if backend not in VALID_BACKENDS:
        raise RuntimeError(
            "LLM_BACKEND must be 'bedrock' or 'api_key' "
            f"(got {backend!r})"
        )
    return backend


def _bedrock_headers(api_url: str, body: bytes) -> Dict[str, str]:
    if boto3 is None or SigV4Auth is None or AWSRequest is None:
        raise RuntimeError(
            "boto3/botocore are required for Bedrock IAM authentication"
        )
    if "bedrock-runtime." not in api_url.lower():
        raise RuntimeError(
            "LLM_BACKEND=bedrock requires a Bedrock Runtime endpoint"
        )

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    profile = os.environ.get("AWS_PROFILE") or None
    session = boto3.Session(profile_name=profile, region_name=region)
    region = session.region_name
    if not region:
        raise RuntimeError(
            "AWS region is not configured. Set AWS_REGION/AWS_DEFAULT_REGION "
            "or configure a default region in the active AWS profile."
        )

    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError(
            "No AWS credentials found. Use AWS SSO/credential chain locally, "
            "or a Lambda execution role in AWS."
        )

    aws_request = AWSRequest(
        method="POST",
        url=api_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(
        credentials.get_frozen_credentials(), "bedrock", region
    ).add_auth(aws_request)
    return dict(aws_request.headers.items())


def _headers(
    backend: str,
    api_url: str,
    body: bytes,
    api_key: Optional[str],
) -> Dict[str, str]:
    if backend == "bedrock":
        # Deliberately ignore any stale API-key variables in Bedrock mode.
        return _bedrock_headers(api_url, body)

    if not api_key:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires the configured stage API key"
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def post_chat_completion(
    api_url: str,
    payload: Dict[str, Any],
    *,
    backend: str,
    api_key: Optional[str] = None,
    timeout_seconds: int = 180,
    max_attempts: int = 2,
) -> Tuple[Dict[str, Any], float]:
    """POST one OpenAI-compatible chat-completions request.

    Only transient transport/service failures are retried here. Semantic/schema
    retries belong to the calling stage so retry layers do not multiply.
    Returns (decoded_response_json, elapsed_seconds_for_successful_attempt).
    """
    backend = backend.strip().lower()
    if backend not in VALID_BACKENDS:
        raise RuntimeError(f"Unsupported LLM backend: {backend!r}")
    if not api_url:
        raise RuntimeError("LLM API URL is not configured")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None

    for attempt in range(1, max_attempts + 1):
        headers = _headers(backend, api_url, body, api_key)
        started = time.time()
        try:
            response = requests.post(
                api_url,
                data=body,
                headers=headers,
                timeout=timeout_seconds,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"LLM request failed: {exc}"
            if attempt >= max_attempts:
                raise RuntimeError(last_error) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        else:
            elapsed = round(time.time() - started, 1)
            if 200 <= response.status_code < 300:
                try:
                    decoded = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        "LLM endpoint returned a non-JSON response"
                    ) from exc
                if not isinstance(decoded, dict):
                    raise RuntimeError("LLM endpoint returned a non-object JSON response")
                return decoded, elapsed

            details = response.text[:1000]
            last_error = f"LLM endpoint returned HTTP {response.status_code}: {details}"
            if response.status_code not in RETRYABLE_STATUS or attempt >= max_attempts:
                raise RuntimeError(last_error)

        # Bounded exponential backoff + jitter for transient failures only.
        time.sleep(min(4.0, (2 ** (attempt - 1)) + random.random()))

    raise RuntimeError(last_error or "LLM request failed")
