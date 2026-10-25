"""Small shared transport for pipeline LLM calls.

Bedrock calls use the Converse SDK operation. Explicit api_key mode uses an
OpenAI-compatible bearer-auth chat-completions endpoint.

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
    from botocore.config import Config
except ImportError:  # clearer error if someone installs only partial deps
    boto3 = None
    Config = None


VALID_BACKENDS = {"bedrock", "api_key"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


def backend_from_env() -> str:
    backend = os.environ.get("LLM_BACKEND", "bedrock").strip().lower()
    if backend not in VALID_BACKENDS:
        raise RuntimeError(
            "LLM_BACKEND must be 'bedrock' or 'api_key' "
            f"(got {backend!r})"
        )
    return backend


def post_chat_completion(
    api_url: str,
    payload: Dict[str, Any],
    *,
    api_key: str,
    timeout_seconds: int = 180,
    max_attempts: int = 2,
) -> Tuple[Dict[str, Any], float]:
    """POST one OpenAI-compatible chat-completions request.

    Only transient transport/service failures are retried here. Semantic/schema
    retries belong to the calling stage so retry layers do not multiply.
    Returns (decoded_response_json, elapsed_seconds_for_successful_attempt).
    """
    if not api_url:
        raise RuntimeError("LLM API URL is not configured")
    if not api_key:
        raise RuntimeError("API-key chat completions require an API key")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_error = None

    for attempt in range(1, max_attempts + 1):
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


def converse(
    model: str,
    system_text: str,
    user_text: str,
    *,
    response_schema: Optional[Dict[str, Any]] = None,
    response_schema_name: str = "priority_assessment_article",
    reasoning: str = "off",
    temperature: Optional[float] = None,
    timeout_seconds: int = 180,
    max_attempts: Optional[int] = None,
) -> Tuple[Dict[str, Any], float]:
    """Call Amazon Bedrock Converse and return its response and elapsed time."""
    if boto3 is None or Config is None:
        raise RuntimeError("boto3/botocore are required for Bedrock Converse")

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    profile = os.environ.get("AWS_PROFILE") or None
    session = boto3.Session(profile_name=profile, region_name=region)
    if not session.region_name:
        raise RuntimeError(
            "AWS region is not configured. Set AWS_REGION/AWS_DEFAULT_REGION "
            "or configure a default region in the active AWS profile."
        )

    request: Dict[str, Any] = {
        "modelId": model,
        "system": [{"text": system_text}],
        "messages": [
            {"role": "user", "content": [{"text": user_text}]},
        ],
    }
    if response_schema is not None:
        request["outputConfig"] = {
            "textFormat": {
                "type": "json_schema",
                "structure": {
                    "jsonSchema": {
                        "name": response_schema_name,
                        "schema": json.dumps(response_schema, ensure_ascii=False),
                    }
                },
            }
        }

    if temperature is not None:
        request["inferenceConfig"] = {"temperature": temperature}

    reasoning = reasoning.strip().lower()
    if reasoning != "off":
        request["additionalModelRequestFields"] = {
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": reasoning},
        }

    config_options: Dict[str, Any] = {
        "connect_timeout": timeout_seconds,
        "read_timeout": timeout_seconds,
    }
    if max_attempts is not None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        config_options["retries"] = {
            "total_max_attempts": max_attempts,
            "mode": "standard",
        }
    client = session.client(
        "bedrock-runtime",
        config=Config(**config_options),
    )
    started = time.time()
    response = client.converse(**request)
    return response, round(time.time() - started, 1)
