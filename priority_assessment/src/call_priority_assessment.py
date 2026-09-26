import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, request

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


def build_request_payload(
    model: str,
    prompt_text: str,
    article_input: Dict[str, Any],
    json_mode: bool = True,
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
        payload["response_format"] = {"type": "json_object"}
    return payload


def call_openai_compatible_chat(
    api_url: str,
    api_key: str,
    model: str,
    prompt_text: str,
    article_input: Dict[str, Any],
    *,
    timeout_seconds: int = 180,
    json_mode: bool = True,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible /chat/completions endpoint.

    The provider is intentionally configurable for Week 9. The pipeline owns the
    handoff/validation contract, not the provider choice.
    """
    payload = build_request_payload(model, prompt_text, article_input, json_mode)
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        api_url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
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
            "Unexpected OpenAI-compatible response shape; missing choices[0].message.content"
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
) -> Dict[str, Any]:
    api_url = api_url or os.getenv("PROMPT2_API_URL")
    api_key = api_key or os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY")
    model = model or os.getenv("PROMPT2_MODEL")

    missing = [
        name
        for name, value in (
            ("PROMPT2_API_URL / --api-url", api_url),
            ("PROMPT2_API_KEY / --api-key", api_key),
            ("PROMPT2_MODEL / --model", model),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing API configuration: " + ", ".join(missing))

    article_input = _load_json(input_path)
    prompt_text = prompt_path.read_text(encoding="utf-8")

    results = call_openai_compatible_chat(
        api_url=api_url,
        api_key=api_key,
        model=model,
        prompt_text=prompt_text,
        article_input=article_input,
        timeout_seconds=timeout_seconds,
        json_mode=json_mode,
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
    parser.add_argument("--api-url")
    parser.add_argument("--api-key")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--plain-json",
        action="store_true",
        help="Do not send response_format=json_object (for providers that do not support it).",
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
    )
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
