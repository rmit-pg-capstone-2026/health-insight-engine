import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "pipeline"))

from llm_transport import (  # noqa: E402
    VALID_BACKENDS,
    backend_from_env,
    converse,
    post_chat_completion,
)

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


def build_user_message(
    article_input: Dict[str, Any],
) -> str:
    return (
        "Execute Priority Assessment article mode on the supplied article insights.\n"
        "Return only JSON matching the required article-mode output.\n\n"
        + json.dumps(article_input, ensure_ascii=False, indent=2)
    )


def _normalise_backend(backend: Optional[str]) -> str:
    backend = (backend or backend_from_env()).strip().lower()
    if backend not in VALID_BACKENDS:
        raise RuntimeError(f"Unsupported LLM backend: {backend!r}")
    return backend


def _chat_payload(
    model: str,
    prompt_text: str,
    user_message: str,
    json_mode: bool,
    response_schema: Optional[Dict[str, Any]],
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": user_message},
        ],
    }

    if temperature is not None:
        payload["temperature"] = temperature

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


def call_priority_assessment(
    model: str,
    prompt_text: str,
    article_input: Dict[str, Any],
    *,
    backend: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_seconds: int = 180,
    json_mode: bool = True,
    response_schema: Optional[Dict[str, Any]] = None,
    reasoning: Optional[str] = None,
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    """Call Priority Assessment through the explicitly selected backend."""
    backend = _normalise_backend(backend)
    reasoning = reasoning if reasoning is not None else os.getenv(
        "PRIORITY_ASSESSMENT_REASONING", "off"
    )
    user_message = build_user_message(article_input)

    if backend == "bedrock":
        bedrock_schema = (
            _bedrock_compatible_schema(response_schema)
            if response_schema is not None
            else None
        )
        envelope, elapsed = converse(
            model,
            prompt_text,
            user_message,
            response_schema=bedrock_schema if json_mode else None,
            reasoning=reasoning,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
            max_attempts=2,
        )
        try:
            blocks = envelope["output"]["message"]["content"]
            content = next(block["text"] for block in blocks if "text" in block)
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Unexpected Bedrock Converse response shape; missing output text"
            ) from exc
        except StopIteration as exc:
            raise RuntimeError(
                "Bedrock Converse response contains no text block"
            ) from exc
    else:
        if not api_url:
            raise RuntimeError(
                "LLM_BACKEND=api_key requires PRIORITY_ASSESSMENT_API_URL"
            )
        if not api_key:
            raise RuntimeError(
                "LLM_BACKEND=api_key requires a Priority Assessment API key"
            )
        payload = _chat_payload(
            model,
            prompt_text,
            user_message,
            json_mode,
            response_schema,
            temperature,
        )
        envelope, elapsed = post_chat_completion(
            api_url,
            payload,
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

    result = parse_model_json(content)

    usage = envelope.get("usage") or {}

    if backend == "bedrock":
        prompt_tokens = usage.get("inputTokens")
        completion_tokens = usage.get("outputTokens")
    else:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")

    return {
        "result": result,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": (
                usage.get("cost_usd", usage.get("cost"))
                if backend == "api_key"
                else None
            ),
        },
        "seconds": elapsed,
    }


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
    temperature: Optional[float] = None,
) -> Dict[str, Any]:
    backend = _normalise_backend(backend)
    api_url = api_url or os.getenv("PRIORITY_ASSESSMENT_API_URL")
    api_key = (
        api_key
        or os.getenv("PRIORITY_ASSESSMENT_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    model = model or os.getenv("PRIORITY_ASSESSMENT_MODEL")

    if not model:
        raise RuntimeError("Set PRIORITY_ASSESSMENT_MODEL or pass --model")
    if backend == "api_key" and not api_url:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires PRIORITY_ASSESSMENT_API_URL"
        )
    if backend == "api_key" and not api_key:
        raise RuntimeError(
            "LLM_BACKEND=api_key requires PRIORITY_ASSESSMENT_API_KEY, "
            "OPENROUTER_API_KEY, or OPENAI_API_KEY"
        )

    article_input = _load_json(input_path)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    response_schema = None
    if json_mode and schema_path is not None:
        response_schema = _load_json(schema_path)

    response = call_priority_assessment(
        model=model,
        prompt_text=prompt_text,
        article_input=article_input,
        backend=backend,
        api_url=api_url,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        json_mode=json_mode,
        response_schema=response_schema,
        temperature=(
            temperature
            if temperature is not None
            else float(os.getenv("PRIORITY_ASSESSMENT_TEMPERATURE", "0.0"))
        ),
    )
    results = response["result"]

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
