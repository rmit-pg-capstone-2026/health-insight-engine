import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from aggregate_assessed_insights import aggregate_assessed_insights
from call_priority_assessment import run_call
from consolidate_insights import consolidate_insights
from prepare_assessment_input import write_outputs
from validate_priority_assessment import load_json, validate_priority_assessment_results


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = ROOT / "prompts" / "priority_assessment_v0.3_article.md"
DEFAULT_SCHEMA = ROOT / "schemas" / "priority_assessment_schema_v0.1.json"


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Week 9 Prompt 1 -> Priority Assessment -> briefing-input pipeline."
    )
    parser.add_argument("prompt1_json", type=Path)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--api-url", default=os.getenv("PROMPT2_API_URL"))
    parser.add_argument("--api-key", default=os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--model", default=os.getenv("PROMPT2_MODEL"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--plain-json", action="store_true")
    parser.add_argument(
        "--assessment-file",
        type=Path,
        help="Use an existing Priority Assessment article-mode result instead of making an API call.",
    )
    args = parser.parse_args()

    input_path = args.prompt1_json.resolve()
    if not input_path.exists():
        parser.error(f"Input file does not exist: {input_path}")

    raw_dir = ROOT / "data" / "raw"
    processed_dir = ROOT / "data" / "processed"
    assessments_dir = ROOT / "data" / "assessments"
    handoff_dir = ROOT / "data" / "handoff"
    for d in (raw_dir, processed_dir, assessments_dir, handoff_dir):
        d.mkdir(parents=True, exist_ok=True)

    audit_copy = raw_dir / input_path.name
    if input_path != audit_copy.resolve():
        shutil.copy2(input_path, audit_copy)

    assessment_input_path = processed_dir / "assessment_input.json"
    review_path = processed_dir / "assessment_review_required.json"
    results_path = assessments_dir / "assessment_results.json"
    assessed_path = processed_dir / "assessed_insights.json"
    briefing_path = handoff_dir / "briefing_input.json"

    print("[1/5] Loading Prompt 1 output...")
    print(f"      {input_path}")

    print("[2/5] Preprocessing / QA...")
    article_input, review_required = write_outputs(
        input_path, assessment_input_path, review_path
    )
    print(
        f"      ready={len(article_input['insights'])}, review_required={len(review_required)}"
    )

    print("[3/5] Running Priority Assessment v0.3 article mode...")
    if not article_input["insights"]:
        assessment_results = {"assessments": []}
        _write_json(results_path, assessment_results)
        print("      no clean insights; API call skipped")
    elif args.assessment_file:
        assessment_results = load_json(args.assessment_file)
        _write_json(results_path, assessment_results)
        print(f"      using existing assessment file: {args.assessment_file}")
    else:
        if not (args.api_url and args.api_key and args.model):
            raise RuntimeError(
                "Priority Assessment API configuration is missing. Set PROMPT2_API_URL, "
                "PROMPT2_API_KEY and PROMPT2_MODEL, or pass --assessment-file."
            )
        assessment_results = run_call(
            assessment_input_path,
            args.prompt,
            results_path,
            api_url=args.api_url,
            api_key=args.api_key,
            model=args.model,
            json_mode=not args.plain_json,
            timeout_seconds=args.timeout,
        )

    expected_ids = [x["insight_id"] for x in article_input["insights"]]
    item_schema = load_json(args.schema)
    validate_priority_assessment_results(assessment_results, expected_ids, item_schema)
    print(f"      validated {len(expected_ids)} assessments")

    print("[4/5] Aggregating...")
    assessed = aggregate_assessed_insights(article_input, assessment_results)
    _write_json(assessed_path, assessed)

    print("[5/5] Consolidating...")
    briefing_input = consolidate_insights(assessed)
    _write_json(briefing_path, briefing_input)

    print(f"Done: {briefing_path}")
    print(f"Review queue: {review_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
