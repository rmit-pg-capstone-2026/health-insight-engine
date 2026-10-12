import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from llm_transport import backend_from_env, post_chat_completion  # noqa: E402

# When run on its own, read settings from the repo-root .env. Anything already
# exported in the shell still wins.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
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
    """Return a Bedrock-compatible copy without changing the repo schema.

    Local validation still uses the full Draft 2020-12 schema. Only the API
    request copy drops constraints that Bedrock structured outputs reject.
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
        "Execute Priority Assessment article mode on the supplied article insights.\n"
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
                    "strict": True,
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
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible chat-completions endpoint.

    Bedrock uses the AWS credential chain + SigV4. API-key mode uses bearer
    authentication. The prompt/output contract is identical for both.
    """
    backend = backend or backend_from_env()
    if response_schema is not None and backend == "bedrock":
        response_schema = _bedrock_compatible_schema(response_schema)

    payload = build_request_payload(
        model,
        prompt_text,
        article_input,
        json_mode=json_mode,
        response_schema=response_schema,
    )
    envelope, _ = post_chat_completion(
        api_url,
        payload,
        backend=backend,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_attempts=2,
    )
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
    backend: Optional[str] = None,
) -> Dict[str, Any]:
    backend = backend or backend_from_env()
    api_url = api_url or os.getenv("PRIORITY_ASSESSMENT_API_URL") or os.getenv("PROMPT2_API_URL")
    api_key = (api_key or os.getenv("PRIORITY_ASSESSMENT_API_KEY")
               or os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY"))
    model = model or os.getenv("PRIORITY_ASSESSMENT_MODEL") or os.getenv("PROMPT2_MODEL")

    missing = [
        name
        for name, value in (
            ("PRIORITY_ASSESSMENT_API_URL / --api-url", api_url),
            ("PRIORITY_ASSESSMENT_MODEL / --model", model),
        )
        if not value
    ]
    if backend == "api_key" and not api_key:
        missing.append("PRIORITY_ASSESSMENT_API_KEY / --api-key")
    if missing:
        raise RuntimeError("Missing API configuration: " + ", ".join(missing))

    article_input = _load_json(input_path)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    response_schema = None
    if json_mode and schema_path is not None:
        response_schema = _load_json(schema_path)

    results = call_openai_compatible_chat(
        api_url=api_url,
        api_key=api_key,
        model=model,
        prompt_text=prompt_text,
        article_input=article_input,
        timeout_seconds=timeout_seconds,
        json_mode=json_mode,
        response_schema=response_schema,
        backend=backend,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Call Priority Assessment in article mode.")
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("assessment_results.json"))
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--api-url")
    parser.add_argument("--api-key")
    parser.add_argument("--model")
    parser.add_argument("--backend", choices=("bedrock", "api_key"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--plain-json",
        action="store_true",
        help="Do not send response_format (local validation can still run separately).",
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
        backend=args.backend,
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
