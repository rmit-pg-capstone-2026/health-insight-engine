import argparse
import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request

try:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
except ImportError:
    boto3 = None
    SigV4Auth = None
    AWSRequest = None

# When run on its own, read PROMPT2_* from the repo-root .env. Anything already
# exported in the shell still wins.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def _strip_optional_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def parse_model_json(text: str) -> Dict[str, Any]:
    cleaned = _strip_optional_code_fence(text)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Priority Assessment API response must be a JSON object")
    return parsed


def _bedrock_compatible_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return an in-memory Bedrock-compatible copy of the article schema.

    The repo schema remains the source of truth and is still used unchanged for
    local Draft 2020-12 validation. Bedrock structured outputs support a subset
    of Draft 2020-12 and reject string/numeric constraints such as minLength.
    """
    unsupported_keywords = {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "multipleOf",
    }

    def clean(value):
        if isinstance(value, dict):
            return {
                key: clean(item)
                for key, item in value.items()
                if key not in unsupported_keywords
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(copy.deepcopy(schema))


def build_request_payload(
    model: str,
    prompt_text: str,
    article_input: Dict[str, Any],
    json_mode: bool = True,
    response_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user_message = (
        "Execute Priority Assessment v0.3 article mode on the supplied article insights.\n"
        "Return only JSON matching the required article-mode output.\n\n"
        + json.dumps(article_input, ensure_ascii=False, indent=2)
    )

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": user_message},
        ],
    }

    if json_mode:
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "priority_assessment_article",
                    "schema": response_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}

    return payload


def call_openai_compatible_chat(
    api_url: str,
    api_key: Optional[str],
    model: str,
    prompt_text: str,
    article_input: Dict[str, Any],
    *,
    timeout_seconds: int = 180,
    json_mode: bool = True,
    response_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible /chat/completions endpoint."""
    payload = build_request_payload(
        model,
        prompt_text,
        article_input,
        json_mode=json_mode,
        response_schema=response_schema,
    )
    body = json.dumps(payload).encode("utf-8")

    headers = {"Content-Type": "application/json"}

    if api_key:
        # Backward-compatible bearer-key authentication.
        headers["Authorization"] = f"Bearer {api_key}"
    elif "bedrock-runtime." in api_url.lower():
        # Use the standard AWS credential chain (for example AWS SSO locally
        # or an IAM execution role after deployment) and sign the request
        # with AWS Signature Version 4.
        if boto3 is None or SigV4Auth is None or AWSRequest is None:
            raise RuntimeError(
                "boto3/botocore are required for Bedrock SigV4 authentication. "
                "Install them with: pip install boto3"
            )

        region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
        profile = os.getenv("AWS_PROFILE")
        session = boto3.Session(profile_name=profile, region_name=region)
        region = session.region_name
        if not region:
            raise RuntimeError(
                "AWS region is not configured. Set AWS_REGION (for example "
                "ap-southeast-2) or configure a default region in your AWS profile."
            )

        credentials = session.get_credentials()
        if credentials is None:
            raise RuntimeError(
                "No AWS credentials found. For local use, log in with your configured "
                "AWS SSO profile, for example: aws sso login --profile rmit-medibank"
            )

        aws_request = AWSRequest(
            method="POST",
            url=api_url,
            data=body,
            headers=headers,
        )
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock", region).add_auth(
            aws_request
        )
        headers = dict(aws_request.headers.items())
    else:
        raise RuntimeError(
            "No API key was supplied and the endpoint is not an AWS Bedrock Runtime "
            "endpoint that can use SigV4 authentication."
        )

    req = request.Request(
        api_url,
        data=body,
        method="POST",
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Priority Assessment API returned HTTP {exc.code}: {details}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Priority Assessment API request failed: {exc}") from exc

    envelope = json.loads(response_body)
    try:
        content = envelope["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Unexpected OpenAI-compatible response shape; "
            "missing choices[0].message.content"
        ) from exc

    if not isinstance(content, str):
        raise RuntimeError("Priority Assessment response content is not a string")

    return parse_model_json(content)


def run_call(
    input_path: Path,
    prompt_path: Path,
    output_path: Path,
    *,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    json_mode: bool = True,
    timeout_seconds: int = 180,
    schema_path: Optional[Path] = None,
) -> Dict[str, Any]:
    api_url = api_url or os.getenv("PROMPT2_API_URL")
    api_key = api_key or os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = model or os.getenv("PROMPT2_MODEL")

    missing = [
        name
        for name, value in (
            ("PROMPT2_API_URL / --api-url", api_url),
            ("PROMPT2_MODEL / --model", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing API configuration: " + ", ".join(missing))

    article_input = _load_json(input_path)
    prompt_text = prompt_path.read_text(encoding="utf-8")

    response_schema = None
    if json_mode and schema_path is not None:
        response_schema = _load_json(schema_path)

        # AWS Bedrock structured outputs use a supported subset of JSON Schema
        # Draft 2020-12. Keep the full schema on disk for local validation, but
        # remove unsupported constraints only from the API request copy.
        if "bedrock-runtime." in api_url.lower():
            response_schema = _bedrock_compatible_schema(response_schema)

    results = call_openai_compatible_chat(
        api_url=api_url,
        api_key=api_key,
        model=model,
        prompt_text=prompt_text,
        article_input=article_input,
        timeout_seconds=timeout_seconds,
        json_mode=json_mode,
        response_schema=response_schema,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call Priority Assessment in article mode."
    )
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("assessment_results.json"),
    )
    parser.add_argument(
        "--schema",
        type=Path,
        help=(
            "Article-mode JSON schema used for structured output. "
            "For Bedrock, unsupported constraints are removed only from "
            "the in-memory API copy."
        ),
    )
    parser.add_argument("--api-url")
    parser.add_argument("--api-key")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--plain-json",
        action="store_true",
        help="Do not send response_format (for providers that do not support it).",
    )
    args = parser.parse_args()

    run_call(
        args.input_json,
        args.prompt,
        args.output,
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model,
        json_mode=not args.plain_json,
        timeout_seconds=args.timeout,
        schema_path=args.schema,
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
