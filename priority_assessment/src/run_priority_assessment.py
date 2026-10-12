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
from validate_priority_assessment import (
    PriorityAssessmentValidationError,
    load_json,
    validate_priority_assessment_results,
)


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
DEFAULT_PROMPT = ROOT / "prompts" / "priority_assessment_v0.3_article.md"
DEFAULT_SCHEMA = ROOT / "schemas" / "priority_assessment_article_schema_v0.1.json"

DEFAULT_INPUT_DIR = REPO_ROOT / "data" / "insight-generated-files"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "priority-tagged-insight-files"

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_results(assessment_results, article_input, article_schema) -> None:
    expected_ids = [x["insight_id"] for x in article_input["insights"]]
    validate_priority_assessment_results(
        assessment_results, expected_ids, article_schema
    )


def process_one(input_path: Path, args, output_dir: Path) -> dict:
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
    review_path = processed_dir / f"{input_path.stem}__assessment_review_required.json"
    results_path = assessments_dir / "assessment_results.json"
    assessed_path = processed_dir / "assessed_insights.json"
    briefing_path = handoff_dir / "briefing_input.json"
    final_path = output_dir / input_path.name

    print("[1/5] Loading Prompt 1 output...")
    print(f"      {input_path}")

    print("[2/5] Preprocessing / QA...")
    article_input, review_required = write_outputs(
        input_path, assessment_input_path, review_path
    )
    print(
        f"      ready={len(article_input['insights'])}, "
        f"review_required={len(review_required)}"
    )

    article_schema = load_json(args.schema)
    expected_ids = [x["insight_id"] for x in article_input["insights"]]

    print("[3/5] Running Priority Assessment v0.3 article mode...")
    if not article_input["insights"]:
        assessment_results = {"assessments": []}
        _write_json(results_path, assessment_results)
        _validate_results(assessment_results, article_input, article_schema)
        print("      no clean insights; API call skipped")
    elif args.assessment_file:
        assessment_results = load_json(args.assessment_file)
        _write_json(results_path, assessment_results)
        _validate_results(assessment_results, article_input, article_schema)
        print(f"      using existing assessment file: {args.assessment_file}")
    else:
        if not (args.api_url and args.model):
            raise RuntimeError(
                "Priority Assessment configuration is missing. Set PROMPT2_API_URL "
                "and PROMPT2_MODEL; API-key mode also needs PROMPT2_API_KEY."
            )

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                print("      retrying Priority Assessment once...")
            assessment_results = run_call(
                assessment_input_path,
                args.prompt,
                results_path,
                api_url=args.api_url,
                api_key=args.api_key,
                model=args.model,
                json_mode=not args.plain_json,
                timeout_seconds=args.timeout,
                schema_path=None if args.plain_json else args.schema,
                backend=args.backend,
            )
            try:
                _validate_results(assessment_results, article_input, article_schema)
                break
            except PriorityAssessmentValidationError as exc:
                if attempt >= max_attempts:
                    raise
                print("      validation failed; requesting one fresh response")
                print(f"      {exc}")

    print(f"      validated {len(expected_ids)} assessments")

    print("[4/5] Aggregating...")
    assessed = aggregate_assessed_insights(article_input, assessment_results)
    _write_json(assessed_path, assessed)

    print("[5/5] Consolidating...")
    briefing_input = consolidate_insights(assessed)
    _write_json(briefing_path, briefing_input)
    _write_json(final_path, briefing_input)

    print(f"Done: {final_path}")
    print(f"Review queue: {review_path}")
    return {
        "ready": len(article_input["insights"]),
        "review": len(review_required),
        "kept": len(briefing_input.get("insights", [])),
        "final_path": final_path,
    }


def run_folder(input_dir: Path, args, output_dir: Path) -> int:
    files = sorted(p for p in input_dir.glob("*.json") if p.is_file())
    if not files:
        raise RuntimeError(f"No .json files found in {input_dir}")

    print(f"Batch: {len(files)} file(s) from {input_dir}")
    print(f"       output to {output_dir}\n")

    done, failed = [], []
    for i, path in enumerate(files, 1):
        print("-" * 74)
        print(f"[{i}/{len(files)}] {path.name}")
        print("-" * 74)
        try:
            done.append((path.name, process_one(path.resolve(), args, output_dir)))
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed.append((path.name, str(exc)))
        print()

    print("=" * 74)
    print("BATCH SUMMARY")
    print("=" * 74)
    for name, info in done:
        print(
            f"  ok      {name}  (ready={info['ready']}, review={info['review']}, "
            f"in briefing={info['kept']})"
        )
    for name, why in failed:
        print(f"  FAILED  {name}  {why}")
    print(f"\n{len(done)} written to {output_dir}, {len(failed)} failed")
    return len(failed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run Prompt 1 -> Priority Assessment -> briefing-input for one "
            "file or every JSON file in a folder."
        )
    )
    parser.add_argument("prompt1_json", type=Path, nargs="?", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--api-url", default=os.getenv("PROMPT2_API_URL"))
    parser.add_argument(
        "--api-key",
        default=os.getenv("PROMPT2_API_KEY") or os.getenv("OPENAI_API_KEY"),
    )
    parser.add_argument("--model", default=os.getenv("PROMPT2_MODEL"))
    parser.add_argument("--backend", choices=("bedrock", "api_key"),
                        default=os.getenv("LLM_BACKEND"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--plain-json", action="store_true")
    parser.add_argument("--assessment-file", type=Path)
    args = parser.parse_args()

    input_path = args.prompt1_json.resolve()
    if not input_path.exists():
        parser.error(f"Input does not exist: {input_path}")
    if not args.schema.exists():
        parser.error(f"Article schema does not exist: {args.schema}")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        if args.assessment_file:
            parser.error("--assessment-file only works with a single input file")
        if run_folder(input_path, args, output_dir):
            raise SystemExit(1)
        return

    process_one(input_path, args, output_dir)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
